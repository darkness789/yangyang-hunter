"""Recover the current board seed during one ordinary game start.

The client uses the same WeChat AES-OFB key and IV for its encrypted request
and response. We temporarily replace the game-start seed token with known
text, derive the OFB stream from the client's request, then restore the
original request ciphertext before forwarding it. The valid server response
is decoded in memory. No user key, IV, stream, token or request is saved.
"""

import base64
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from mitmproxy import http


OUTPUT = Path(os.environ.get("YLGY_CAPTURE_DIR", "captures"))
GAME_START = "/sheep/v1/game/world/game_start"
SEED_PATH = "/sheep/v1/game/map_info_ex_seed"
CHOSEN_SEED = "A" * 96


def read_varint(buf, offset):
    value = 0
    shift = 0
    while offset < len(buf):
        byte = buf[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 128:
            return value, offset
        shift += 7
        if shift > 70:
            raise ValueError("invalid varint")
    raise ValueError("truncated varint")


def decode_seed_ack(buf):
    result = {"code": None, "mapSeed": [], "mapSeed2": ""}
    offset = 0
    while offset < len(buf):
        tag, offset = read_varint(buf, offset)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = read_varint(buf, offset)
            if field == 1:
                result["code"] = value
            elif field == 2:
                result["mapSeed"].append(value)
        elif wire == 2:
            length, offset = read_varint(buf, offset)
            value = buf[offset:offset + length]
            if len(value) != length:
                raise ValueError("truncated seed field")
            offset += length
            if field == 2:
                cursor = 0
                while cursor < len(value):
                    number, cursor = read_varint(value, cursor)
                    result["mapSeed"].append(number)
            elif field == 3:
                result["mapSeed2"] = value.decode("utf-8")
        else:
            raise ValueError("unsupported seed wire type")
    if result["code"] != 1 or len(result["mapSeed"]) != 4:
        raise ValueError("seed response did not decode as a successful four-number seed")
    return result


def seed_request(seed):
    raw = seed.encode("utf-8")
    if len(raw) >= 128:
        raise ValueError("seed token too long for this probe")
    return bytes((10, len(raw))) + raw


def read_request_info(flow):
    body = flow.request.get_text()
    content_type = flow.request.headers.get("content-type", "").lower()
    if "application/x-www-form-urlencoded" in content_type:
        pairs = parse_qsl(body, keep_blank_values=True)
        info = next((value for key, value in pairs if key == "info"), None)
        if info is None:
            raise ValueError("form request has no info field")
        return info, ("form", pairs)
    payload = json.loads(body)
    return payload["info"], ("json", payload)


def write_request_info(flow, parsed, info):
    kind, data = parsed
    if kind == "form":
        body = urlencode([(key, info if key == "info" else value)
                          for key, value in data])
    else:
        data["info"] = info
        body = json.dumps(data, separators=(",", ":"))
    flow.request.set_text(body)


class SeedProbe:
    def __init__(self):
        self.pending_seed2 = None
        self.pending_map_md5 = None

    def response(self, flow: http.HTTPFlow):
        if flow.request.pretty_host != "cat-match.easygame2021.com":
            return
        path = flow.request.path.split("?", 1)[0]
        if flow.response.status_code != 200:
            return
        if path == GAME_START:
            try:
                payload = json.loads(flow.response.get_text())
                data = payload["data"]
                if not data.get("need_seed"):
                    return
                seed2 = data["map_seed_2"]
                if not isinstance(seed2, str) or not seed2:
                    return
                self.pending_seed2 = seed2
                self.pending_map_md5 = data.get("map_md5")
                data["map_seed_2"] = CHOSEN_SEED
                flow.response.set_text(json.dumps(payload, separators=(",", ":")))
                print("[seed-probe] Prepared one-start seed recovery", flush=True)
            except (ValueError, KeyError, TypeError) as exc:
                print(f"[seed-probe] Could not inspect game start: {exc}", flush=True)
        elif path == SEED_PATH and "ylgy_probe_stream" in flow.metadata:
            try:
                stream = flow.metadata.pop("ylgy_probe_stream")
                ciphertext = bytes(flow.response.get_content(strict=False) or b"")
                if len(ciphertext) > len(stream):
                    raise ValueError("response longer than known OFB stream")
                plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
                seed = decode_seed_ack(plaintext)
                OUTPUT.mkdir(parents=True, exist_ok=True)
                (OUTPUT / "recovered_seed.json").write_text(json.dumps({
                    "map_md5": flow.metadata.pop("ylgy_probe_map_md5"),
                    "map_seed": seed["mapSeed"],
                    "map_seed_2": seed["mapSeed2"],
                    "method": "one-start AES-OFB known-plaintext probe",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                print("[seed-probe] Recovered current board seed; saved recovered_seed.json", flush=True)
            except Exception as exc:
                print(f"[seed-probe] Response decode failed: {type(exc).__name__}: {exc}", flush=True)

    def request(self, flow: http.HTTPFlow):
        if flow.request.pretty_host != "cat-match.easygame2021.com":
            return
        if flow.request.path.split("?", 1)[0] != SEED_PATH:
            return
        if self.pending_seed2 is None:
            return
        try:
            info, parsed = read_request_info(flow)
            framed = base64.b64decode(info, validate=True)
            known = seed_request(CHOSEN_SEED)
            if len(framed) != 3 + len(known) or framed[0] != 1:
                raise ValueError("unexpected encrypted request frame")
            stream = bytes(a ^ b for a, b in zip(framed[3:], known))
            original = seed_request(self.pending_seed2)
            restored = framed[:3] + bytes(a ^ b for a, b in zip(original, stream))
            write_request_info(flow, parsed, base64.b64encode(restored).decode("ascii"))
            flow.metadata["ylgy_probe_stream"] = stream
            flow.metadata["ylgy_probe_map_md5"] = self.pending_map_md5
            self.pending_seed2 = None
            self.pending_map_md5 = None
            print("[seed-probe] Restored valid seed request before forwarding", flush=True)
        except Exception as exc:
            print(f"[seed-probe] Request probe failed: {type(exc).__name__}: {exc}", flush=True)


addons = [SeedProbe()]
