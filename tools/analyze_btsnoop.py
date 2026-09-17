#!/usr/bin/env python3
"""Extract BLE ATT writes from an Android Bluetooth HCI snoop log.

The tool intentionally stays offline: it reads a local ``btsnoop_hci.log`` and
prints only protocol metadata and byte streams.  This is useful for comparing
a known-good Android print against the bytes produced by ``encoder.js``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


BTSNOOP_EPOCH_US = 0x00DC_DDB3_0F2F_8000
HCI_ACL = 0x02
HCI_EVENT = 0x04
ATT_CID = 0x0004
ATT_WRITE_REQUEST = 0x12
ATT_WRITE_COMMAND = 0x52


@dataclass(frozen=True)
class Record:
    timestamp_us: int
    flags: int
    data: bytes

    @property
    def received(self) -> bool:
        return bool(self.flags & 1)

    @property
    def timestamp(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(
            (self.timestamp_us - BTSNOOP_EPOCH_US) / 1_000_000,
            tz=dt.timezone.utc,
        )


@dataclass(frozen=True)
class AttWrite:
    timestamp: dt.datetime
    connection_handle: int
    attribute_handle: int
    opcode: int
    value: bytes


@dataclass(frozen=True)
class RfcommPayload:
    timestamp: dt.datetime
    connection_handle: int
    remote_cid: int
    dlci: int
    value: bytes


def read_records(path: Path) -> Iterator[Record]:
    with path.open("rb") as stream:
        header = stream.read(16)
        if len(header) != 16 or header[:8] != b"btsnoop\x00":
            raise ValueError(f"{path} no es un archivo btsnoop válido")

        version, datalink = struct.unpack(">II", header[8:])
        if version != 1 or datalink != 1002:
            raise ValueError(
                f"Formato HCI inesperado (versión={version}, datalink={datalink})"
            )

        while record_header := stream.read(24):
            if len(record_header) != 24:
                raise ValueError("Registro btsnoop truncado")
            _, included_length, flags, _, timestamp_us = struct.unpack(
                ">IIIIq", record_header
            )
            data = stream.read(included_length)
            if len(data) != included_length:
                raise ValueError("Carga útil btsnoop truncada")
            yield Record(timestamp_us=timestamp_us, flags=flags, data=data)


def connection_events(records: Iterator[Record]) -> dict[int, str]:
    """Return LE connection-handle -> peer MAC mappings announced by HCI."""
    handles: dict[int, str] = {}
    for record in records:
        data = record.data
        # BR/EDR Connection Complete: status, handle, BD_ADDR, link type,
        # encryption.  The Android app uses this transport for the P1.
        if len(data) >= 14 and data[0] == HCI_EVENT and data[1] == 0x03:
            if data[3] == 0:
                handle = struct.unpack_from("<H", data, 4)[0] & 0x0FFF
                address = ":".join(f"{byte:02X}" for byte in data[6:12][::-1])
                handles[handle] = address
            continue
        if len(data) < 6 or data[0] != HCI_EVENT or data[1] != 0x3E:
            continue
        parameters = data[3 : 3 + data[2]]
        if not parameters:
            continue
        subevent = parameters[0]
        # LE Connection Complete and LE Enhanced Connection Complete share this
        # prefix: status, connection handle, role, peer-address type, address.
        if subevent not in (0x01, 0x0A) or len(parameters) < 12:
            continue
        if parameters[1] != 0:
            continue
        handle = struct.unpack_from("<H", parameters, 2)[0] & 0x0FFF
        address = ":".join(f"{byte:02X}" for byte in parameters[6:12][::-1])
        handles[handle] = address
    return handles


def att_writes(records: Iterator[Record]) -> Iterator[AttWrite]:
    """Yield host-to-controller ATT write requests/commands.

    P1 writes are short enough to fit in one ATT/L2CAP frame.  L2CAP
    continuation fragments are deliberately ignored here rather than guessed;
    the tool reports only complete first fragments with an ATT payload.
    """
    for record in records:
        if record.received:
            continue
        data = record.data
        if len(data) < 10 or data[0] != HCI_ACL:
            continue
        handle_and_flags, acl_length = struct.unpack_from("<HH", data, 1)
        acl = data[5 : 5 + acl_length]
        if len(acl) < 8:
            continue
        packet_boundary = (handle_and_flags >> 12) & 0b11
        if packet_boundary not in (0, 2):
            continue
        l2cap_length, cid = struct.unpack_from("<HH", acl)
        if cid != ATT_CID or len(acl) < 4 + l2cap_length:
            continue
        att = acl[4 : 4 + l2cap_length]
        if len(att) < 3 or att[0] not in (ATT_WRITE_REQUEST, ATT_WRITE_COMMAND):
            continue
        yield AttWrite(
            timestamp=record.timestamp,
            connection_handle=handle_and_flags & 0x0FFF,
            attribute_handle=struct.unpack_from("<H", att, 1)[0],
            opcode=att[0],
            value=att[3:],
        )


def rfcomm_payloads(records: Iterator[Record]) -> Iterator[RfcommPayload]:
    """Yield host-to-device RFCOMM UIH payloads carried in Classic Bluetooth.

    Android's official P1 app opens a BR/EDR RFCOMM channel (PSM 3).  Its UIH
    frames carry the printer command bytes directly.  Each observed frame fits
    in a single L2CAP packet; incomplete ACL fragments are skipped safely.
    """
    for record in records:
        if record.received:
            continue
        data = record.data
        if len(data) < 10 or data[0] != HCI_ACL:
            continue
        handle_and_flags, acl_length = struct.unpack_from("<HH", data, 1)
        acl = data[5 : 5 + acl_length]
        if len(acl) < 8:
            continue
        packet_boundary = (handle_and_flags >> 12) & 0b11
        if packet_boundary not in (0, 2):
            continue
        l2cap_length, cid = struct.unpack_from("<HH", acl)
        if cid in (0, 1, 4) or len(acl) < 4 + l2cap_length:
            continue
        rfcomm = acl[4 : 4 + l2cap_length]
        if len(rfcomm) < 4 or rfcomm[1] != 0xEF:  # UIH information frame
            continue
        if rfcomm[2] & 1:
            payload_length, payload_start = rfcomm[2] >> 1, 3
        else:
            if len(rfcomm) < 5 or not (rfcomm[3] & 1):
                continue
            payload_length = (rfcomm[2] >> 1) | ((rfcomm[3] >> 1) << 7)
            payload_start = 4
        payload_end = payload_start + payload_length
        # One final byte is RFCOMM's FCS.  Reject malformed frames instead of
        # accidentally treating a following packet as printer data.
        if len(rfcomm) != payload_end + 1:
            continue
        yield RfcommPayload(
            timestamp=record.timestamp,
            connection_handle=handle_and_flags & 0x0FFF,
            remote_cid=cid,
            dlci=rfcomm[0] >> 2,
            value=rfcomm[payload_start:payload_end],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Ruta a btsnoop_hci.log")
    parser.add_argument(
        "--device",
        type=str.upper,
        help="Filtra por MAC de la impresora, p. ej. B8:50:44:0C:9E:39",
    )
    parser.add_argument(
        "--stream-out",
        type=Path,
        help="Guarda la concatenación de bytes de impresión del transporte elegido",
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "att", "rfcomm"),
        default="auto",
        help="Transporte a analizar; auto prioriza RFCOMM si hay tráfico Classic",
    )
    args = parser.parse_args()

    records = list(read_records(args.log))
    handles = connection_events(iter(records))
    print("Conexiones Bluetooth detectadas:")
    for handle, address in sorted(handles.items()):
        print(f"  handle 0x{handle:04X}: {address}")

    allowed_handles = {
        handle for handle, address in handles.items() if not args.device or address == args.device
    }
    writes = [
        write
        for write in att_writes(iter(records))
        if not args.device or write.connection_handle in allowed_handles
    ]
    rfcomm = [
        payload
        for payload in rfcomm_payloads(iter(records))
        if not args.device or payload.connection_handle in allowed_handles
    ]

    print(f"\nEscrituras ATT salientes: {len(writes)}")
    by_attribute: dict[int, int] = defaultdict(int)
    for write in writes:
        by_attribute[write.attribute_handle] += 1
        kind = "request" if write.opcode == ATT_WRITE_REQUEST else "command"
        print(
            f"{write.timestamp.isoformat()} handle=0x{write.connection_handle:04X} "
            f"attr=0x{write.attribute_handle:04X} {kind} "
            f"len={len(write.value):02d} {write.value.hex()}"
        )
    if by_attribute:
        summary = ", ".join(
            f"0x{attribute:04X}={count}" for attribute, count in sorted(by_attribute.items())
        )
        print(f"\nResumen por atributo: {summary}")

    print(f"\nTramas RFCOMM UIH salientes: {len(rfcomm)}")
    by_channel: dict[tuple[int, int], int] = defaultdict(int)
    for payload in rfcomm:
        by_channel[payload.remote_cid, payload.dlci] += 1
        print(
            f"{payload.timestamp.isoformat()} handle=0x{payload.connection_handle:04X} "
            f"cid=0x{payload.remote_cid:04X} dlci={payload.dlci} "
            f"len={len(payload.value):03d} {payload.value.hex()}"
        )
    if by_channel:
        summary = ", ".join(
            f"cid=0x{cid:04X}/dlci={dlci}: {count}"
            for (cid, dlci), count in sorted(by_channel.items())
        )
        print(f"\nResumen RFCOMM: {summary}")

    if args.stream_out:
        if args.transport == "att":
            stream = b"".join(write.value for write in writes)
        elif args.transport == "rfcomm":
            stream = b"".join(payload.value for payload in rfcomm)
        else:
            stream = b"".join(payload.value for payload in rfcomm) or b"".join(
                write.value for write in writes
            )
        args.stream_out.write_bytes(stream)
        print(f"Stream guardado: {args.stream_out} ({len(stream)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
