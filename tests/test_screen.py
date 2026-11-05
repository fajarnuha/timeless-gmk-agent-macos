from unittest.mock import Mock, patch
import unittest

from PIL import Image

from agent_animations import AGENTS, FRAME_COUNTS, SIZE, frames
from kbd_screen import FRAME_BYTES, animation_data, encode_frame, upload
from kbd_time_sync import Kbd


class ScreenTests(unittest.TestCase):
    def test_rgb565_high_byte_first_and_frame_padding(self):
        image = Image.new("RGB", SIZE, (255, 0, 0))
        data = encode_frame(image)
        self.assertEqual(data[:4], b"\xf8\x00\xf8\x00")
        self.assertEqual(len(data), FRAME_BYTES)
        self.assertEqual(set(data[240 * 135 * 2:]), {0})

    def test_all_animations_have_distinct_frames_and_fit_memory(self):
        self.assertLessEqual(sum(FRAME_COUNTS.values()), 36)
        for agent in AGENTS:
            for event, count in FRAME_COUNTS.items():
                images = frames(agent, event)
                self.assertEqual(len(images), count)
                self.assertTrue(all(image.size == SIZE for image in images))
                self.assertEqual(len({image.tobytes() for image in images}), count)

    def test_bank_windows_point_to_exact_animation_frames(self):
        data, windows = animation_data()
        self.assertEqual(len(data), 36 * FRAME_BYTES)
        for (agent, event), (display, first, second) in windows.items():
            offset, count = (0, first) if display == 1 else (first, second)
            expected = b"".join(encode_frame(image) for image in frames(agent, event))
            self.assertEqual(data[offset * FRAME_BYTES:(offset + count) * FRAME_BYTES], expected)
            self.assertLessEqual(first + second, 36)

    def test_upload_preserves_unrelated_settings_and_positions(self):
        keyboard = Mock()
        cfg = list(range(48))
        data = b"\xaa" * (FRAME_BYTES * 2)
        upload(keyboard, data, (1, 1), cfg)
        written = keyboard.write_config.call_args.args[0]
        changed = {34, 46, 43, 44, *range(35, 42)}
        for offset in set(range(48)) - changed:
            self.assertEqual(written[offset], cfg[offset])
        self.assertEqual(keyboard.cmd.call_args_list[0].args, (0x23,))
        chunks = [call.args for call in keyboard.cmd.call_args_list if call.args[0] == 0x21]
        self.assertEqual(b"".join(call[1] for call in chunks), data)
        self.assertEqual([call[2] for call in chunks], list(range(0, len(data), 56)))
        self.assertEqual(keyboard.cmd.call_args_list[-1].args, (2,))

    def test_invalid_config_or_upload_fails_before_usb_write(self):
        keyboard = Mock()
        with self.assertRaises(ValueError):
            upload(keyboard, b"", (0, 0), [0] * 48)
        keyboard.cmd.assert_not_called()
        device = Kbd.__new__(Kbd)
        device.cmd = Mock()
        with self.assertRaises(ValueError):
            device.write_config([0] * 47)
        device.cmd.assert_not_called()

    def test_hid_report_checksum_and_matching_reply(self):
        keyboard = Kbd.__new__(Kbd)
        keyboard.dev = Mock()
        def write(report):
            self.assertEqual(report[0], 4)
            self.assertEqual(report[3:8], [0x21, 2, 0x56, 0x34, 0x12])
            self.assertEqual(report[8:10], [0xAB, 0xCD])
            self.assertEqual(report[1] | report[2] << 8, sum(report[3:]))
            keyboard.dev.read.side_effect = [[4, 0, 0, 0], [0, 0, 0, 0x21, 1, 2, 3, 4]]
            return 64
        keyboard.dev.write.side_effect = write
        self.assertEqual(keyboard.cmd(0x21, [0xAB, 0xCD], 0x123456), [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
