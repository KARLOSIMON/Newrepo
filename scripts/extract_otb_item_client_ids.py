#!/usr/bin/env python3
"""Extract native server-id -> client-id pairs from a TFS items.otb file.\n\nOA-1 source-of-truth extractor; output feeds the client DAT native-ID migration.

This implements only the OTB framing and item attributes needed by RPGGAME OA-1.
It follows the pinned TFS fileloader/items loader:
- identifier: 4 bytes
- node start/end/escape: FE / FF / FD
- item props: uint32 flags followed by TLV attributes
- ITEM_ATTR_SERVERID = 0x10
- ITEM_ATTR_CLIENTID = 0x11
"""
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path

START = 0xFE
END = 0xFF
ESCAPE = 0xFD
ITEM_ATTR_SERVERID = 0x10
ITEM_ATTR_CLIENTID = 0x11


@dataclass
class Node:
    node_type: int
    props: bytes
    children: list["Node"]


def parse_node(data: bytes, offset: int) -> tuple[Node, int]:
    if offset >= len(data) or data[offset] != START:
        raise ValueError(f"expected OTB node start at offset {offset}")
    if offset + 1 >= len(data):
        raise ValueError("truncated OTB node type")

    node_type = data[offset + 1]
    offset += 2
    props = bytearray()
    children: list[Node] = []

    while offset < len(data):
        byte = data[offset]
        if byte == ESCAPE:
            if offset + 1 >= len(data):
                raise ValueError("truncated OTB escape")
            props.append(data[offset + 1])
            offset += 2
            continue
        if byte == START:
            child, offset = parse_node(data, offset)
            children.append(child)
            continue
        if byte == END:
            return Node(node_type=node_type, props=bytes(props), children=children), offset + 1

        props.append(byte)
        offset += 1

    raise ValueError("unterminated OTB node")


def parse_item_record(node_type: int, props: bytes) -> dict[str, int] | None:
    if len(props) < 4:
        return None
    flags = struct.unpack_from("<I", props, 0)[0]
    offset = 4
    server_id = None
    client_id = None

    while offset < len(props):
        if offset + 3 > len(props):
            raise ValueError("truncated item attribute header")
        attr = props[offset]
        length = struct.unpack_from("<H", props, offset + 1)[0]
        offset += 3
        end = offset + length
        if end > len(props):
            raise ValueError("truncated item attribute payload")
        payload = props[offset:end]
        offset = end

        if attr == ITEM_ATTR_SERVERID:
            if length != 2:
                raise ValueError("server-id attribute is not uint16")
            server_id = struct.unpack("<H", payload)[0]
        elif attr == ITEM_ATTR_CLIENTID:
            if length != 2:
                raise ValueError("client-id attribute is not uint16")
            client_id = struct.unpack("<H", payload)[0]

    if server_id is None or client_id is None:
        return None
    return {
        "server_id": server_id,
        "client_id": client_id,
        "group": node_type,
        "flags": flags,
    }


def extract_records(path: Path) -> dict[int, dict[str, int]]:
    data = path.read_bytes()
    if len(data) < 7:
        raise ValueError("items.otb is too small")
    if data[:4] not in (b"OTBI", bytes(4)):
        raise ValueError(f"unexpected OTB identifier: {data[:4]!r}")

    root, end_offset = parse_node(data, 4)
    if end_offset != len(data):
        trailing = data[end_offset:]
        if any(byte != 0 for byte in trailing):
            raise ValueError("unexpected nonzero bytes after root OTB node")

    records: dict[int, dict[str, int]] = {}
    for child in root.children:
        record = parse_item_record(child.node_type, child.props)
        if record is not None:
            records[record["server_id"]] = record
    if not records:
        raise ValueError("no item server/client ID pairs found")
    return records


def extract_mapping(path: Path) -> dict[int, int]:
    return {
        server_id: record["client_id"]
        for server_id, record in extract_records(path).items()
    }


def self_test() -> None:
    child_props = (
        struct.pack("<I", 0)
        + bytes([ITEM_ATTR_SERVERID]) + struct.pack("<H", 2) + struct.pack("<H", 431)
        + bytes([0x20]) + struct.pack("<H", 1) + bytes([0xFE])
        + bytes([ITEM_ATTR_CLIENTID]) + struct.pack("<H", 2) + struct.pack("<H", 460)
    )
    escaped = bytearray()
    for byte in child_props:
        if byte in (START, END, ESCAPE):
            escaped.append(ESCAPE)
        escaped.append(byte)

    data = b"OTBI" + bytes([START, 0x00, START, 0x01]) + bytes(escaped) + bytes([END, END])
    root, end_offset = parse_node(data, 4)
    assert end_offset == len(data)
    assert len(root.children) == 1
    assert parse_item_record(root.children[0].node_type, root.children[0].props) == {
        "server_id": 431,
        "client_id": 460,
        "group": 1,
        "flags": 0,
    }
    print("items.otb parser self-test: PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("otb", nargs="?", type=Path)
    parser.add_argument("--ids", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        if args.otb is None:
            return

    if args.otb is None:
        parser.error("otb path is required unless --self-test is used alone")

    records = extract_records(args.otb)
    requested = [int(value) for value in args.ids.split(",") if value.strip()]
    if requested:
        missing = [item_id for item_id in requested if item_id not in records]
        if missing:
            raise SystemExit(f"server item IDs missing from OTB: {missing}")
        records = {item_id: records[item_id] for item_id in requested}

    if args.details:
        if args.json:
            print(json.dumps({str(k): v for k, v in sorted(records.items())}, indent=2))
        else:
            print(",".join(
                f"{server_id}={record['client_id']}:{record['group']}:{record['flags']}"
                for server_id, record in sorted(records.items())
            ))
        return

    mapping = {server_id: record["client_id"] for server_id, record in records.items()}
    if args.json:
        print(json.dumps({str(k): v for k, v in sorted(mapping.items())}, indent=2))
    else:
        print(",".join(f"{server_id}={client_id}" for server_id, client_id in sorted(mapping.items())))


if __name__ == "__main__":
    main()
