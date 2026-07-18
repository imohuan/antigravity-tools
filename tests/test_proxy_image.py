"""图片处理单元测试 —— 验证代理中转时的图片格式归一化、历史图片剥离、inline图片过滤

覆盖场景：
1. input_image → image_url 格式转换（Codex/WorkBuddy 发图的真实格式）
2. 历史图片替换为文字描述
3. inline/base64 图片被剔除（上游 copilot.tencent.com/v2 不接受）
4. _build_workbuddy_relay_body 全链路集成测试
5. 真实图片 test.png 的 base64 编码 → input_image 格式 → 归一化验证

运行：
    python -m pytest tests/test_proxy_image.py -v
    或
    python -m unittest tests.test_proxy_image -v
"""

import base64
import copy
import json
import os
import sys
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.modules.proxy_server import (
    _image_url_from_part,
    _normalize_messages_for_upstream,
    _remove_unsupported_inline_images,
    _strip_history_images_with_description,
    _build_workbuddy_relay_body,
    _part_is_image,
    _detect_multimodal_images,
)

_TEST_IMAGE_PATH = r"D:\Code\Git\web2api\images\test.png"


def _load_test_image_base64():
    if not os.path.exists(_TEST_IMAGE_PATH):
        return None
    with open(_TEST_IMAGE_PATH, "rb") as f:
        data = f.read()
    return f"data:image/png;base64,{base64.b64encode(data).decode()}"


class TestImageUrlFromPart(unittest.TestCase):

    def test_standard_image_url(self):
        part = {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}
        self.assertEqual(_image_url_from_part(part), "https://example.com/img.png")

    def test_image_url_detail(self):
        part = {"type": "image_url", "image_url": {"url": "https://example.com/img.png", "detail": "high"}}
        self.assertEqual(_image_url_from_part(part), "https://example.com/img.png")

    def test_image_url_string(self):
        part = {"type": "image_url", "image_url": "https://example.com/img.png"}
        self.assertEqual(_image_url_from_part(part), "https://example.com/img.png")

    def test_input_image_with_url(self):
        part = {"type": "input_image", "url": "https://example.com/photo.jpg"}
        self.assertEqual(_image_url_from_part(part), "https://example.com/photo.jpg")

    def test_input_image_with_source_url(self):
        part = {"type": "input_image", "source": {"type": "url", "url": "https://example.com/pic.jpg"}}
        self.assertEqual(_image_url_from_part(part), "https://example.com/pic.jpg")

    def test_input_image_with_source_base64(self):
        part = {
            "type": "input_image",
            "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"},
        }
        result = _image_url_from_part(part)
        self.assertTrue(result.startswith("data:image/png;base64,"))

    def test_image_type_with_url(self):
        part = {"type": "image", "url": "https://example.com/photo.jpg"}
        self.assertEqual(_image_url_from_part(part), "https://example.com/photo.jpg")

    def test_image_type_with_image_dict(self):
        part = {"type": "image", "image": {"url": "https://example.com/img.png"}}
        self.assertEqual(_image_url_from_part(part), "https://example.com/img.png")

    def test_image_type_with_image_data(self):
        b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        part = {"type": "image", "image": {"data": b64, "mediaType": "image/jpeg"}}
        result = _image_url_from_part(part)
        self.assertTrue(result.startswith("data:image/jpeg;base64,"))

    def test_non_image_part(self):
        part = {"type": "text", "text": "hello"}
        self.assertIsNone(_image_url_from_part(part))

    def test_non_dict_part(self):
        self.assertIsNone(_image_url_from_part("hello"))
        self.assertIsNone(_image_url_from_part(42))


class TestNormalizeMessagesForUpstream(unittest.TestCase):

    def test_single_input_image_to_image_url(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "这张图片是什么？"},
                {"type": "input_image", "url": "https://example.com/test.png"},
            ],
        }]
        messages = copy.deepcopy(messages); count = _normalize_messages_for_upstream(messages)
        self.assertEqual(count, 1)
        parts = messages[0]["content"]
        image_part = parts[1]
        self.assertEqual(image_part["type"], "image_url")
        self.assertEqual(image_part["image_url"]["url"], "https://example.com/test.png")

    def test_multiple_input_images(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "input_image", "url": "https://example.com/a.png"},
                {"type": "input_image", "url": "https://example.com/b.png"},
                {"type": "input_image", "url": "https://example.com/c.png"},
            ],
        }]
        messages = copy.deepcopy(messages); count = _normalize_messages_for_upstream(messages)
        self.assertEqual(count, 3)
        for part in messages[0]["content"]:
            self.assertEqual(part["type"], "image_url")

    def test_image_url_preserved(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
            ],
        }]
        messages = copy.deepcopy(messages); count = _normalize_messages_for_upstream(messages)
        self.assertEqual(count, 0)

    def test_text_parts_preserved(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "描述这张图"},
                {"type": "input_image", "url": "https://example.com/test.png"},
            ],
        }]
        _normalize_messages_for_upstream(messages)
        self.assertEqual(messages[0]["content"][0]["type"], "text")
        self.assertEqual(messages[0]["content"][0]["text"], "描述这张图")

    def test_mixed_image_types(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "input_image", "url": "https://example.com/a.png"},
                {"type": "image", "url": "https://example.com/b.png"},
                {"type": "image_url", "image_url": {"url": "https://example.com/c.png"}},
            ],
        }]
        messages = copy.deepcopy(messages); count = _normalize_messages_for_upstream(messages)
        self.assertEqual(count, 2)

    def test_base64_image_passed_through(self):
        b64_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        messages = [{
            "role": "user",
            "content": [
                {"type": "input_image", "url": b64_uri},
            ],
        }]
        messages = copy.deepcopy(messages); count = _normalize_messages_for_upstream(messages)
        self.assertEqual(count, 1, 'base64 也应该被归一化')
        self.assertEqual(messages[0]['content'][0]['type'], 'image_url')


class TestRemoveUnsupportedInlineImages(unittest.TestCase):

    def test_http_url_image_kept(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
            ],
        }]
        removed = _remove_unsupported_inline_images(messages)
        self.assertEqual(removed, 0)

    def test_base64_image_url_removed(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"}},
            ],
        }]
        removed = _remove_unsupported_inline_images(messages)
        self.assertEqual(removed, 1)
        self.assertTrue(any(p["type"] == "text" and "Image omitted" in p["text"]
                           for p in messages[0]["content"]))

    def test_input_image_removed(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "input_image", "url": "https://example.com/img.png"},
            ],
        }]
        removed = _remove_unsupported_inline_images(messages)
        self.assertEqual(removed, 1)

    def test_mixed_images(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://example.com/ok.png"}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                {"type": "input_image", "url": "https://example.com/bad.png"},
            ],
        }]
        removed = _remove_unsupported_inline_images(messages)
        self.assertEqual(removed, 2)


class TestStripHistoryImagesWithDescription(unittest.TestCase):

    def test_single_image_kept(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": [
                {"type": "text", "text": "这是什么？"},
                {"type": "input_image", "url": "https://example.com/img.png"},
            ]},
        ]
        result = _strip_history_images_with_description(messages)
        content = result[1]["content"]
        image_types = [p.get("type") for p in content]
        self.assertIn("input_image", image_types)

    def test_two_user_images_last_kept(self):
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "第一张图"},
                {"type": "input_image", "url": "https://example.com/old.png"},
            ]},
            {"role": "assistant", "content": "我看到第一张图了"},
            {"role": "user", "content": [
                {"type": "text", "text": "第二张图"},
                {"type": "input_image", "url": "https://example.com/new.png"},
            ]},
        ]
        result = _strip_history_images_with_description(messages)
        first_content = result[0]["content"]
        first_image_types = [p.get("type") for p in first_content]
        self.assertNotIn("input_image", first_image_types)
        last_content = result[2]["content"]
        last_image_types = [p.get("type") for p in last_content]
        self.assertIn("input_image", last_image_types)

    def test_no_images_unchanged(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _strip_history_images_with_description(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], "hello")

    def test_assistant_with_image_between(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "input_image", "url": "https://example.com/img.png"}]},
            {"role": "assistant", "content": "分析中..."},
        ]
        result = _strip_history_images_with_description(messages)
        content = result[0]["content"]
        image_types = [p.get("type") for p in content]
        self.assertIn("input_image", image_types)


class TestBuildWorkbuddyRelayBody(unittest.TestCase):

    def test_simple_text_request(self):
        body = {"model": "auto", "messages": [{"role": "user", "content": "hello"}]}
        upstream_body, meta = _build_workbuddy_relay_body(body)
        self.assertEqual(upstream_body["stream"], True)
        self.assertEqual(meta["mode"], "workbuddy_relay")
        self.assertEqual(meta["normalized_images"], 0)

    def test_input_image_converted_to_image_url(self):
        body = {
            "model": "auto",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "描述这张图"},
                    {"type": "input_image", "url": "https://example.com/test.png"},
                ],
            }],
        }
        upstream_body, meta = _build_workbuddy_relay_body(body)
        self.assertGreater(meta["normalized_images"], 0)
        image_parts = [p for p in upstream_body["messages"][0]["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(image_parts), 1)
        self.assertEqual(image_parts[0]["image_url"]["url"], "https://example.com/test.png")

    def test_original_body_not_mutated(self):
        body = {
            "model": "auto",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "input_image", "url": "https://example.com/test.png"},
                ],
            }],
        }
        _build_workbuddy_relay_body(body)
        self.assertEqual(body["messages"][0]["content"][0]["type"], "input_image")

    def test_empty_model_defaults_to_auto(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        upstream_body, _ = _build_workbuddy_relay_body(body)
        self.assertEqual(upstream_body["model"], "auto")

    def test_max_completion_tokens_translation(self):
        body = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "max_completion_tokens": 4096,
        }
        _, meta = _build_workbuddy_relay_body(body)
        self.assertIn("max_completion_tokens->max_tokens", meta["translated_fields"])

    def test_null_fields_removed(self):
        body = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": None,
        }
        upstream_body, meta = _build_workbuddy_relay_body(body)
        self.assertNotIn("temperature", upstream_body)
        self.assertIn("temperature", meta["removed_null_fields"])

    def test_stream_options_detected(self):
        body = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream_options": {"include_usage": True},
        }
        _, meta = _build_workbuddy_relay_body(body)
        self.assertTrue(meta["has_stream_options"])


class TestDetectMultimodalImages(unittest.TestCase):

    def test_no_images(self):
        body = {"messages": [{"role": "user", "content": "hello"}]}
        stats = _detect_multimodal_images(body)
        self.assertEqual(stats["image_count"], 0)

    def test_single_image(self):
        body = {"messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ]}]}
        stats = _detect_multimodal_images(body)
        self.assertEqual(stats["image_count"], 1)

    def test_base64_data_uri_detected(self):
        body = {"messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
        ]}]}
        stats = _detect_multimodal_images(body)
        self.assertEqual(stats["image_count"], 1)
        self.assertEqual(stats["data_uri_count"], 1)

    def test_input_image_detected(self):
        body = {"messages": [{"role": "user", "content": [
            {"type": "input_image", "url": "https://example.com/img.png"},
        ]}]}
        stats = _detect_multimodal_images(body)
        self.assertEqual(stats["image_count"], 1)

    def test_real_test_image_base64_size(self):
        b64_uri = _load_test_image_base64()
        if not b64_uri:
            self.skipTest("test.png not found")
        body = {"messages": [{"role": "user", "content": [
            {"type": "input_image", "url": b64_uri},
        ]}]}
        stats = _detect_multimodal_images(body)
        self.assertEqual(stats["image_count"], 1)
        self.assertEqual(stats["data_uri_count"], 1)
        self.assertGreater(stats["max_image_chars"], 1000)


class TestFullPipelineWithRealImage(unittest.TestCase):

    def test_input_image_url_to_upstream_format(self):
        body = {
            "model": "auto",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "描述这张图的文本内容"},
                    {"type": "input_image", "url": "https://example.com/test.png"},
                ],
            }],
        }
        upstream_body, meta = _build_workbuddy_relay_body(body)
        content = upstream_body["messages"][0]["content"]
        image_url_parts = [p for p in content if p.get("type") == "image_url"]
        self.assertTrue(len(image_url_parts) > 0, "input_image 应该被转为 image_url")
        self.assertEqual(image_url_parts[0]["image_url"]["url"], "https://example.com/test.png")
        text_parts = [p for p in content if p.get("type") == "text"]
        self.assertTrue(len(text_parts) > 0, "文本部分应该保留")
        self.assertGreater(meta["normalized_images"], 0)

    def test_multiturn_with_images(self):
        body = {
            "model": "auto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": [
                    {"type": "text", "text": "第一轮看图"},
                    {"type": "input_image", "url": "https://example.com/old.png"},
                ]},
                {"role": "assistant", "content": "第一张图我看到了"},
                {"role": "user", "content": [
                    {"type": "text", "text": "第二轮看图"},
                    {"type": "input_image", "url": "https://example.com/new.png"},
                ]},
            ],
        }
        upstream_body, meta = _build_workbuddy_relay_body(body)
        self.assertEqual(meta['history_images_replaced'], 0, '代理不管历史图片')
        last_user_msg = upstream_body["messages"][3]
        all_image_url_parts = [p for p in last_user_msg["content"] if p.get("type") == "image_url"]
        self.assertTrue(len(all_image_url_parts) > 0, "两张图都应转为 image_url 格式")


if __name__ == "__main__":
    unittest.main(verbosity=2)


