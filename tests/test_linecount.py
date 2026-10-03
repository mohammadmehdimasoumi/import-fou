from fou.inspection.linecount import count_plain_lines, count_python_lines


def stats(src, ranges=()):
    s, prefix = count_python_lines(src, list(ranges))
    return s, prefix


def test_blank_comment_code_are_separated():
    src = "# header\n\nx = 1  # trailing\n\n# c\ny = 2\n"
    s, _ = stats(src)
    assert (s.total, s.code, s.blank, s.comment, s.docstring) == (6, 2, 2, 2, 0)


def test_hash_inside_string_is_code_not_comment():
    s, _ = stats('x = "# not a comment"\n')
    assert (s.code, s.comment) == (1, 0)


def test_multiline_string_counts_every_line_as_code():
    s, _ = stats('x = """a\nb\n# c\n"""\n')
    assert s.code == 4 and s.comment == 0


def test_docstring_lines_are_not_code():
    src = 'def f():\n    """one\n    two\n    """\n    return 1\n'
    s, prefix = stats(src, [(2, 4)])
    assert (s.code, s.docstring) == (2, 3)
    assert prefix[5] - prefix[0] == 2


def test_one_line_def_with_docstring_is_code():
    s, _ = stats('def f(): """doc"""\n', [(1, 1)])
    assert (s.code, s.docstring) == (1, 0)


def test_continuation_lines_and_inner_comments():
    src = "x = (1 +\n     # inner\n     2)\n"
    s, _ = stats(src)
    assert (s.code, s.comment) == (2, 1)


def test_empty_source():
    s, prefix = stats("")
    assert (s.total, s.code) == (0, 0) and prefix == [0]


def test_no_trailing_newline():
    s, _ = stats("x = 1")
    assert (s.total, s.code) == (1, 1)


def test_tokenize_failure_falls_back_to_approximation():
    s, _ = stats("x = (1,\n# c\n\ny = 2\n")
    assert s.precise is False and s.total == 4 and s.code >= 1


def test_plain_lines_are_non_blank_and_imprecise():
    s = count_plain_lines("a\n\nb\n  \n")
    assert (s.total, s.code, s.blank, s.precise) == (4, 2, 2, False)
