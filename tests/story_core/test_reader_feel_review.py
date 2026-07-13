from packages.story_core.reader_feel_review import review_reader_feel


def test_reader_feel_review_rejects_near_duplicate_paragraphs():
    body = "\n\n".join(
        [
            "夜烬把多出的毒腺压到背包底下。旁边的人只看见他没交任务，也没领铜币，只当他还差两份材料。",
            "他绕到坡口又杀了一只灰狼，捡起狼皮后看了一眼法力，转身回村。",
            "夜烬把剩下的毒腺压在背包底下。旁边玩家只看见他没有交任务，也没有领铜币，只当他还缺两份材料。",
        ]
    )

    review = review_reader_feel(body)

    assert review["pass"] is False
    assert review["scores"]["patchwork"] <= 5
    assert review["metrics"]["near_duplicate_count"] == 1
    assert review["duplicate_pairs"]


def test_reader_feel_review_allows_repeated_subject_in_distinct_actions():
    body = "\n\n".join(
        [
            "夜烬抬起法杖，等灰狼冲过石头才放出火球。",
            "夜烬退到树后喝下蓝药，顺手把新捡的狼皮塞进背包。",
            "夜烬回村交了任务，又问洛婶下一项前置任务要去哪里接。",
        ]
    )

    review = review_reader_feel(body)

    assert review["pass"] is True
    assert review["scores"]["patchwork"] == 8
    assert review["metrics"]["near_duplicate_count"] == 0


def test_reader_feel_review_catches_repeated_sentences_inside_one_paragraph():
    body = (
        "旁人只看见他没交任务、没领铜币，也没往柜台递东西。"
        "夜烬把背包关上，转身走向灰狼坡外侧。"
        "队伍里的玩家只当他运气不错，随口让他别挡窗口。"
        "旁人只看见他没有交任务、没有领铜币，也没有往柜台递东西。"
    )

    review = review_reader_feel(body)

    assert review["pass"] is False
    assert review["metrics"]["near_duplicate_count"] == 1
