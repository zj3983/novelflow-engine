import pytest

from packages.story_core.title_strategy import (
    build_book_title_guidance,
    build_chapter_title_guidance,
    validate_chapter_title_window,
)


def test_book_guidance_uses_natural_three_part_strategy_and_protects_examples():
    guidance = build_book_title_guidance("game_webnovel")

    assert "核心卖点或特殊能力" in guidance
    assert "主角身份或反差" in guidance
    assert "爽点或后果" in guidance
    assert "按自然中文重新组织" in guidance
    assert "只学结构，不得照抄" in guidance


@pytest.mark.parametrize(
    ("genre_id", "expected_terms"),
    [
        ("game_webnovel", ("全服", "Boss")),
        ("xuanhuan", ("宗门", "血脉")),
        ("xianxia", ("天劫", "飞升")),
        ("urban", ("合同", "职业")),
        ("suspense", ("嫌疑人", "时间线")),
        ("rules_mystery", ("规则", "污染")),
        ("romance", ("承诺", "边界")),
        ("generic_webnovel", ("目标", "代价")),
    ],
)
def test_book_guidance_uses_genre_specific_vocabulary(genre_id, expected_terms):
    guidance = build_book_title_guidance(genre_id)

    assert all(term in guidance for term in expected_terms)
    if genre_id != "game_webnovel":
        assert "全服" not in guidance
        assert "Boss" not in guidance


def test_game_examples_never_leak_into_non_game_guidance():
    game = build_book_title_guidance("game_webnovel")
    xuanhuan = build_book_title_guidance("xuanhuan")

    assert "满级魔龙" in game
    assert "满级魔龙" not in xuanhuan
    assert "结构示例" not in xuanhuan


@pytest.mark.parametrize("genre_id", ["网游", "GAME_WEBNOVEL", " game_webnovel "])
def test_genre_id_is_normalized_before_selecting_terms_and_examples(genre_id):
    guidance = build_book_title_guidance(genre_id)

    assert "全服" in guidance
    assert "Boss" in guidance
    assert "满级魔龙" in guidance


def test_custom_genre_uses_extra_terms_without_game_vocabulary():
    guidance = build_book_title_guidance(
        "custom_science_fantasy",
        extra_terms=("星门", "量子回响"),
    )

    assert "星门" in guidance
    assert "量子回响" in guidance
    assert "全服" not in guidance
    assert "Boss" not in guidance


def test_bare_string_extra_terms_is_treated_as_one_term():
    guidance = build_chapter_title_guidance("urban", extra_terms="量子回响")

    assert "量子回响" in guidance
    assert "量、子、回、响" not in guidance


def test_chapter_guidance_requires_event_evidence_and_supported_directions():
    guidance = build_chapter_title_guidance("urban")

    assert "必须对应本章真实发生的事件" in guidance
    assert all(shape in guidance for shape in ("危机", "反击", "反差", "悬念", "转折"))
    assert "不要重复写章节编号" in guidance
    assert "相邻三章" in guidance


@pytest.mark.parametrize(
    ("suffix", "shape"),
    [("？", "question"), ("!", "exclamation")],
)
def test_three_identical_expressive_shapes_are_rejected(suffix, shape):
    chapters = [
        {"chapter_number": 1, "title": f"开局就要退婚{suffix}"},
        {"chapter_number": 2, "title": f"第一次谈判就翻脸{suffix}"},
        {"chapter_number": 3, "title": f"刚拿合同就反悔{suffix}"},
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(chapters, genre_id="urban")

    assert str(exc_info.value) == f"repeated_chapter_title_shape:{shape}:1-3"


@pytest.mark.parametrize(
    ("titles", "shape"),
    [
        (("《谁动了合同？》", "“真相在哪？”", "【谁在撒谎？】"), "question"),
        (("《合同归我！》", "“现在反击！”", "【当场翻盘！】"), "exclamation"),
    ],
)
def test_title_shape_ignores_trailing_wrapper_punctuation(titles, shape):
    chapters = [
        {"chapter_number": number, "title": title}
        for number, title in enumerate(titles, start=1)
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(chapters, genre_id="urban")

    assert str(exc_info.value) == f"repeated_chapter_title_shape:{shape}:1-3"


def test_previous_chapter_tail_is_included_in_title_window_validation():
    previous_chapters = [
        {"chapter_number": 8, "title": "旧案重启"},
        {"chapter_number": 9, "title": "证人为什么改口？"},
        {"chapter_number": 10, "title": "监控为何消失？"},
    ]
    new_chapters = [{"chapter_number": 11, "title": "合同是谁替换的？"}]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(
            new_chapters,
            genre_id="urban",
            previous_chapters=previous_chapters,
        )

    assert str(exc_info.value) == "repeated_chapter_title_shape:question:9-11"


def test_mixed_title_shapes_are_accepted():
    chapters = [
        {"chapter_number": 4, "title": "第4章 合同竟然是假的？"},
        {"chapter_number": 5, "chapter_title": "当场夺回签字权！"},
        {"chapter_number": 6, "title": "幕后股东现身"},
    ]

    assert validate_chapter_title_window(chapters, genre_id="urban") is None


def test_sparse_generated_numbers_are_not_treated_as_consecutive_positions():
    generated = [
        {"chapter_number": 14, "title": "第十四章谁动了合同？"},
        {"chapter_number": 16, "title": "第十六章真相在哪？"},
        {"chapter_number": 17, "title": "第十七章谁在撒谎？"},
    ]

    assert (
        validate_chapter_title_window(
            generated,
            genre_id="urban",
            known_chapters=[{"chapter_number": 15, "title": "第十五章落定"}],
            generated_chapter_numbers={14, 16, 17},
        )
        is None
    )


def test_known_chapter_completes_a_consecutive_generated_title_triple():
    generated = [
        {"chapter_number": 14, "title": "第十四章谁动了合同？"},
        {"chapter_number": 16, "title": "第十六章谁在撒谎？"},
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(
            generated,
            genre_id="urban",
            known_chapters=[{"chapter_number": 15, "title": "第十五章真相在哪？"}],
            generated_chapter_numbers={14, 16},
        )

    assert str(exc_info.value) == "repeated_chapter_title_shape:question:14-16"


def test_generated_nonempty_titles_override_known_duplicates_without_empty_erasure():
    generated = [
        {"chapter_number": 14, "title": "生成标题为什么改变？"},
        {"chapter_number": 14, "title": ""},
        {"chapter_number": 16, "title": "第十六章真相在哪？"},
    ]
    known = [
        {"chapter_number": 14, "title": "已有陈述标题"},
        {"chapter_number": 15, "title": "第十五章谁动了合同？"},
        {"chapter_number": 15, "title": ""},
    ]

    with pytest.raises(ValueError, match="question:14-16"):
        validate_chapter_title_window(
            generated,
            genre_id="urban",
            known_chapters=known,
            generated_chapter_numbers={14, 16},
        )


def test_old_title_triples_without_generated_chapters_do_not_block_current_window():
    known = [
        {"chapter_number": 1, "title": "旧问题一？"},
        {"chapter_number": 2, "title": "旧问题二？"},
        {"chapter_number": 3, "title": "旧问题三？"},
    ]

    assert (
        validate_chapter_title_window(
            [{"chapter_number": 10, "title": "当前任务已落定"}],
            genre_id="urban",
            known_chapters=known,
            generated_chapter_numbers={10},
        )
        is None
    )


def test_duplicate_chapter_title_within_same_batch_is_rejected():
    generated = [
        {"chapter_number": 10, "title": "玄渊降临"},
        {"chapter_number": 15, "title": "第15章 玄渊降临"},
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(
            generated,
            genre_id="xuanhuan",
            generated_chapter_numbers={10, 15},
        )

    assert str(exc_info.value) == "duplicate_chapter_title:15:10:第15章 玄渊降临"


def test_duplicate_chapter_title_across_distant_known_chapters_is_rejected():
    known = [
        {"chapter_number": 198, "title": "第198章 玄渊降临"},
    ]
    generated = [
        {"chapter_number": 209, "title": "《玄渊降临》"},
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(
            generated,
            genre_id="xuanhuan",
            known_chapters=known,
            generated_chapter_numbers={209},
        )

    assert str(exc_info.value) == "duplicate_chapter_title:209:198:《玄渊降临》"


def test_select_all_existing_chapter_titles_aggregates_and_sorts_correctly():
    from packages.story_core.title_strategy import select_all_existing_chapter_titles

    source1 = [{"chapter_number": 1, "title": "短路与穿越"}, {"chapter_number": 2, "title": "无灵根"}]
    source2 = [{"chapter_number": 2, "title": "无灵根的杂役"}, {"chapter_number": 3, "title": "灵气的本质"}]

    all_titles = select_all_existing_chapter_titles(source1, source2)
    assert all_titles == [
        {"chapter_number": 1, "title": "短路与穿越"},
        {"chapter_number": 2, "title": "无灵根的杂役"},
        {"chapter_number": 3, "title": "灵气的本质"},
    ]
