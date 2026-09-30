"""Exercise the product HTTP contract against the explicitly offline server only."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8531")
    parser.add_argument("--chapters", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--book")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.url, timeout=120)
    evidence = []
    confirmed_bodies = {}
    book_id = args.book

    def record(event, **values):
        entry = {"event": event, **values}
        evidence.append(entry)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    def view(chapter=None):
        params = {"book_id": book_id} if book_id else {}
        if chapter is not None:
            params["chapter"] = chapter
        response = client.get("/author-workspace", params=params)
        assert response.headers.get("x-novelflow-synthetic") == "longform-offline", "Refusing a non-synthetic server"
        response.raise_for_status()
        return response.json()

    def book(chapter=None):
        return next(b for b in view(chapter)["books"] if b["id"] == book_id)

    def idle():
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            b = book()
            if not b["busy"]:
                return b
            time.sleep(0.5)
        raise AssertionError("Task did not finish within 900 seconds")

    def send(name, *, token=None, **values):
        state = view() if name == "create" else book()
        action = state["actions"][name]
        assert token or action["enabled"], (name, state.get("notice"), action)
        response = client.post("/author-workspace/commands", json={
            "bookId": book_id, "token": token or action["token"], "command": {"type": name, **values}})
        if token:
            return response
        assert response.is_success, (name, response.status_code, response.text)
        return response.json()

    if not book_id:
        result = send("create", title="离线长程验收", genre="generic_webnovel", idea="林照核对祖祠旧档，逐步查清宗门旧案。",
                      targetWords=900000, chapterWords=3000, requirements="每次核对保留依据。")
        book_id = result["bookId"]
        record("created", book=book_id, confirmed=len(book()["chapters"]))
        send("prepare-directions")
        b = idle()
        assert b.get("directions"), b.get("notice")
        direction = b["directions"][0]
        send("direction", id=direction["id"], text=direction["text"])

    def plan():
        for _ in range(20):
            b = idle()
            if b["planAdopted"] and (b.get("candidate") or b["actions"]["generate"]["enabled"]):
                return
            if b["actions"]["adopt"]["enabled"]:
                send("adopt")
                record("adopted", volume=b["planningVolume"])
                return
            for action in ("next-volume", "sync-plan", "complete-volume", "prepare-plan", "refresh-plan", "continue-plan"):
                if b["actions"].get(action, {}).get("enabled"):
                    record("planning", action=action)
                    send(action)
                    break
            else:
                raise AssertionError(("No planning action", b.get("notice"), b["actions"]))
        raise AssertionError("Planning did not converge")

    for prior in book()["chapters"]:
        saved = next(c for c in book(prior["number"])["chapters"] if c["number"] == prior["number"])
        confirmed_bodies[prior["number"]] = hashlib.sha256(saved["body"].encode()).hexdigest()
    plan()
    for number in range(len(book()["chapters"]) + 1, args.chapters + 1):
        b = idle()
        if not b.get("candidate"):
            if not b["actions"]["generate"]["enabled"]:
                plan()
            send("generate")
            b = idle()
        if not b.get("candidate"):
            record("generation-failure", chapter=number, notice=b.get("notice"))
            assert number in {17, 18}, b
            send("generate")
            b = idle()
        assert b.get("candidate"), (number, b.get("notice"))
        assert b["candidate"]["number"] == number
        assert len(b["chapters"]) == number - 1
        if number == 18 and b["candidate"]["needsCheck"]:
            body_before = b["candidate"]["body"]
            assert not b["actions"]["confirm"]["enabled"]
            denied = send("confirm", token=b["actions"]["confirm"]["token"], **{"continue": False})
            assert denied.status_code == 409
            record("review-failure", chapter=number, confirmation_rejected=True)
            send("review")
            b = idle()
            assert b["candidate"]["body"] == body_before
            record("review-recovered", chapter=number, body_preserved=True)
        if number == 3:
            old_token = b["actions"]["confirm"]["token"]
            edited = b["candidate"]["body"] + "\n林照把核对日期记在纸页边上。"
            send("save-draft", text=edited)
            b = idle()
            assert b["candidate"]["body"] == edited and b["candidate"]["needsCheck"]
            assert not b["actions"]["confirm"]["enabled"]
            assert send("confirm", token=old_token, **{"continue": False}).status_code == 409
            send("review")
            b = idle()
            record("manual-edit-rechecked", chapter=number)
        if number == 4:
            send("ai-edit", instruction="补充核对记录的细节，保留已发生的事件。")
            b = idle()
            record("ai-edit-rechecked", chapter=number)
        assert b["candidate"]["canConfirm"] or b["candidate"].get("canAcceptSuggestion"), (number, b["candidate"].get("concerns"), b.get("notice"))
        confirm = "confirm" if b["actions"]["confirm"]["enabled"] else "accept-suggestion"
        old_token = b["actions"][confirm]["token"]
        confirmed_bodies[number] = hashlib.sha256(b["candidate"]["body"].encode()).hexdigest()
        send(confirm, **{"continue": number == 7})
        after = idle()
        assert len(after["chapters"]) == number
        assert not after.get("candidate") or number == 7 and after["candidate"]["number"] == 8
        duplicate = send(confirm, token=old_token, **{"continue": False}) if confirm in after["actions"] else client.post(
            "/author-workspace/commands", json={"bookId": book_id, "token": old_token, "command": {"type": confirm, "continue": False}})
        assert duplicate.status_code == 409
        assert len(book()["chapters"]) == number
        record("confirmed", chapter=number, volume=after["planningVolume"], duplicate_rejected=True)
    for number, expected in confirmed_bodies.items():
        response = client.get("/author-workspace", params={"book_id": book_id, "chapter": number})
        response.raise_for_status()
        selected = next(b for b in response.json()["books"] if b["id"] == book_id)
        chapter = next(c for c in selected["chapters"] if c["number"] == number)
        assert hashlib.sha256(chapter["body"].encode()).hexdigest() == expected
    record("complete", book=book_id, chapters=args.chapters, confirmed_bodies_unchanged=len(confirmed_bodies))


if __name__ == "__main__":
    main()
