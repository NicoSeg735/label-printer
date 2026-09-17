import socket
import unittest
from unittest.mock import MagicMock, patch

from printer import RFCOMM_MAX_PAYLOAD, _send_rfcomm_payload


class RfcommTransportTests(unittest.TestCase):
    @patch("printer.time.sleep")
    @patch("printer.socket.socket")
    def test_sends_a_native_stream_over_channel_one_in_captured_sized_frames(
        self, socket_factory, _sleep
    ):
        client = MagicMock()
        socket_factory.return_value = client

        _send_rfcomm_payload("B8:50:44:0C:9E:39", b"a" * 130)

        socket_factory.assert_called_once_with(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        client.connect.assert_called_once_with(("B8:50:44:0C:9E:39", 1))
        self.assertEqual(
            [call.args[0] for call in client.sendall.call_args_list],
            [b"a" * RFCOMM_MAX_PAYLOAD, b"a" * 8],
        )
        client.close.assert_called_once()

    def test_rejects_frames_larger_than_the_verified_rfcomm_payload(self):
        with self.assertRaises(ValueError):
            _send_rfcomm_payload("B8:50:44:0C:9E:39", b"a", chunk_size=123)


if __name__ == "__main__":
    unittest.main()
