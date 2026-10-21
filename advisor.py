"""Local browser advisor for one fully decoded Sheep Planet board."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from board_model import Board, IllegalMove
from solve import depth_search, replay


class Session:
    def __init__(self, board, branches, seconds):
        self.board = board
        self.branches = branches
        self.seconds = seconds
        self.clicked = []
        self.plan = []
        self.search = {"status": "not_started"}

    def current(self):
        state = self.board.initial()
        for tile_id in self.clicked:
            state = self.board.move(state, tile_id)
        return state

    def solve(self):
        state = self.current()
        result = depth_search(self.board, self.seconds,
                              initial_state=state,
                              max_branches=self.branches)
        self.search = {key: value for key, value in result.items() if key != "path"}
        self.plan = ([self.board.tiles[index].id for index in result["path"]]
                     if result["status"] == "solved" and
                     replay(self.board, result["path"], state) else [])

    def public(self):
        state = self.current()
        visible = set(self.board.visible_indices(state))
        return {
            "tiles": [{"id": tile.id, "type": tile.type, "x": tile.x,
                       "y": tile.y, "layer": tile.layer, "mold": tile.mold,
                       "visible": index in visible,
                       "removed": bool(state.removed & (1 << index))}
                      for index, tile in enumerate(self.board.tiles)],
            "clicked": self.clicked,
            "tray": {str(index): count for index, count in enumerate(state.tray)
                     if count},
            "plan_length": len(self.plan),
            "next": self.plan[0] if self.plan else None,
            "search": self.search,
            "won": self.board.won(state),
            "lost": state.lost,
        }


def make_handler(session):
    page = (Path(__file__).parent / "static" / "index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, value):
            content = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/api/state":
                self.send_json(200, session.public())
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 4096:
                    raise ValueError("request is too large")
                body = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/solve":
                    session.solve()
                elif self.path == "/api/move":
                    tile_id = body.get("id")
                    if not isinstance(tile_id, str):
                        raise ValueError("tile id is required")
                    current = session.current()
                    next_state = session.board.move(current, tile_id)
                    if next_state.lost:
                        raise ValueError("that move fills all seven tray slots")
                    expected = session.plan[0] if session.plan else None
                    session.clicked.append(tile_id)
                    if expected == tile_id:
                        session.plan.pop(0)
                    else:
                        session.plan = []
                        session.search = {"status": "needs_replan"}
                elif self.path == "/api/undo":
                    if session.clicked:
                        session.clicked.pop()
                    session.plan = []
                    session.search = {"status": "needs_replan"}
                else:
                    self.send_json(404, {"error": "not found"})
                    return
                self.send_json(200, session.public())
            except (ValueError, IllegalMove, KeyError) as exc:
                self.send_json(400, {"error": str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("map_file", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--branches", type=int, default=5)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    board = Board.from_json(args.map_file)
    if any(tile.type <= 0 for tile in board.tiles):
        parser.error("map types are missing; restore the seed first")
    session = Session(board, args.branches, args.seconds)
    server = HTTPServer(("127.0.0.1", args.port), make_handler(session))
    print("Open http://127.0.0.1:{}/ in your browser".format(args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
