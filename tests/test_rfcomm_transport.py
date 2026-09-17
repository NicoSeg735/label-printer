import socket
import unittest
from unittest.mock import MagicMock, patch

from printer import (
    RFCOMM_MAX_PAYLOAD,
    _send_rfcomm_payload,
    normalize_bluetooth_address,
    print_via_classic,
    validate_rfcomm_settings,
)


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
        client.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        client.close.assert_called_once()

    def test_rejects_frames_larger_than_the_verified_rfcomm_payload(self):
        with self.assertRaises(ValueError):
            _send_rfcomm_payload("B8:50:44:0C:9E:39", b"a", chunk_size=123)

    def test_normalizes_common_mac_format_and_rejects_invalid_configuration(self):
        self.assertEqual(normalize_bluetooth_address("b8-50-44-0c-9e-39"), "B8:50:44:0C:9E:39")
        with self.assertRaisesRegex(ValueError, "Dirección Bluetooth inválida"):
            validate_rfcomm_settings("P1-40608023", 1, 15)
        with self.assertRaisesRegex(ValueError, "entre 1 y 120"):
            validate_rfcomm_settings("B8:50:44:0C:9E:39", 1, 0)

    @patch("printer.socket.socket", side_effect=OSError("adaptador deshabilitado"))
    def test_socket_creation_error_has_an_actionable_message(self, _socket_factory):
        with self.assertRaisesRegex(ConnectionError, "emparejado"):
            _send_rfcomm_payload("B8:50:44:0C:9E:39", b"stream")

    def test_refuses_an_empty_print_job_before_opening_a_connection(self):
        with self.assertRaisesRegex(ValueError, "No hay etiquetas"):
            print_via_classic([])


if __name__ == "__main__":
    unittest.main()
