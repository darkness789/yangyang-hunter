"""Decode the captured .map template format used by the observed game build.

This parses the protobuf wire format directly, using the public GameMap schema
documented by BugMaker888/sheep. It does not infer card types from the seed.
"""

import argparse
import json
from pathlib import Path


def fields(data):
    pos = 0

    def varint():
        nonlocal pos
        value = 0
        shift = 0
        while pos < len(data):
            byte = data[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value
            shift += 7
            if shift > 70:
                raise ValueError("invalid varint")
        raise ValueError("truncated varint")

    while pos < len(data):
        tag = varint()
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value = varint()
        elif wire == 2:
            length = varint()
            value = data[pos:pos + length]
            if len(value) != length:
                raise ValueError("truncated field")
            pos += length
        elif wire == 1:
            value = data[pos:pos + 8]
            pos += 8
        elif wire == 5:
            value = data[pos:pos + 4]
            pos += 4
        else:
            raise ValueError("unsupported protobuf wire type %d" % wire)
        yield field, value


def scalar_message(data):
    return dict(fields(data))


def decode_node(data):
    raw = scalar_message(data)
    return {
        "id": raw.get(1, b"").decode("utf-8"),
        "type": raw.get(2, 0),
        "rolNum": raw.get(3, 0),
        "rowNum": raw.get(4, 0),
        "layerNum": raw.get(5, 0),
        "moldType": raw.get(6, 0),
        "metaType": raw.get(7, 0),
    }


def decode_map(path):
    raw = Path(path).read_bytes()
    if not raw.startswith(b".map") or len(raw) < 22:
        raise ValueError("not a recognized .map file")
    result = {"widthNum": 0, "heightNum": 0, "levelKey": 0,
              "blockTypeData": {}, "levelData": {}}
    for field, value in fields(raw[21:]):
        if field == 1:
            result["widthNum"] = value
        elif field == 2:
            result["heightNum"] = value
        elif field == 3:
            result["levelKey"] = value
        elif field == 4:
            item = scalar_message(value)
            result["blockTypeData"][item[1].decode("utf-8")] = item[2]
        elif field == 5:
            item = scalar_message(value)
            layer = item[1].decode("utf-8")
            result["levelData"][layer] = [
                decode_node(node) for kind, node in fields(item[2]) if kind == 1
            ]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("map_file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-map-md5", help="map identifier from the same game_start response")
    args = parser.parse_args()
    decoded = decode_map(args.map_file)
    if args.source_map_md5:
        decoded["sourceMapMd5"] = args.source_map_md5
    nodes = [node for layer in decoded["levelData"].values() for node in layer]
    summary = {
        "levelKey": decoded["levelKey"],
        "size": [decoded["widthNum"], decoded["heightNum"]],
        "layers": {key: len(value) for key, value in decoded["levelData"].items()},
        "blocks": len(nodes),
        "preset_types": sum(node["type"] > 0 for node in nodes),
        "type_groups": decoded["blockTypeData"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(decoded, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
