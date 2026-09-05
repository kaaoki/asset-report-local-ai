"""
pdf_exporter.py
LLMが生成したMarkdown形式のレポート文字列を、日本語対応PDFに変換する。

日本語を表示するには Unicode 対応のTTFフォントが必要。
IPAex明朝/ゴシック(IPAフォントライセンスにより無料・再配布可)の利用を想定し、
fonts/ipaexg.ttf に配置する前提にしている(READMEのセットアップ手順を参照)。
"""

from __future__ import annotations

import os
import re

from fpdf import FPDF

DEFAULT_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "ipaexg.ttf")


class PdfExportError(Exception):
    """PDF生成に失敗した場合に送出する。"""


# 行頭に来てはいけない文字(禁則処理・行頭禁則)
_KINSOKU_LINE_START_FORBIDDEN = set(
    "、。,.・:;!?」』)】〕》〉]}ー" "ぁぃぅぇぉゃゅょっァィゥェォャュョッ"
)


# 英字・数字・数値中の記号(カンマ・ピリオド・符号・%)は「1つの単語/数値」として
# まとめて扱う(この中では改行しない)。日本語文字はこれに含まれず、1文字ずつ
# 改行可能な位置として扱われる。
_ATOM_EXTRA_CHARS = set("+-.,%")


def _is_atom_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in _ATOM_EXTRA_CHARS)


def _tokenize_for_wrap(text: str) -> list[str]:
    """折り返し処理用に、英数字/数値の連続を1トークンにまとめて分割する。

    例: "eMAXIS Slim" -> ["eMAXIS", " ", "Slim"]
        "1,402,000円" -> ["1,402,000", "円"]
    日本語文字はそれぞれ独立した1文字トークンになる(どこでも改行可能)。
    """
    atoms: list[str] = []
    current = ""
    for ch in text:
        if _is_atom_char(ch):
            current += ch
        else:
            if current:
                atoms.append(current)
                current = ""
            atoms.append(ch)
    if current:
        atoms.append(current)
    return atoms


def _wrap_with_kinsoku(pdf: FPDF, text: str, max_width: float) -> list[str]:
    """fpdf2の標準wrapは禁則処理(行頭に句読点等を置かない)や、英単語・数値の
    途中で改行しない、といった処理に対応していないため、独自に折り返す。

    - 英数字・数値のまとまり(トークン)は途中で分割しない
    - 行頭禁則文字が次に来る場合、現在行の末尾1文字を道連れにして次の行へ送る
      (オイダシ)。各行の幅は必ずmax_width以内に収める(はみ出しを許容すると
      fpdf2のmulti_cell側で再ラップされ、禁則処理が無効化されてしまうため)。
    """
    atoms = _tokenize_for_wrap(text)
    lines: list[str] = []
    current_atoms: list[str] = []
    current_str = ""
    for atom in atoms:
        trial = current_str + atom
        if current_atoms and pdf.get_string_width(trial) > max_width:
            first_char = atom[0]
            if first_char in _KINSOKU_LINE_START_FORBIDDEN and len(current_atoms) > 1:
                # 現在行の最後の"トークン"(1文字とは限らない)を道連れにして
                # 次の行へ送る。文字単位で道連れにすると英単語や数値の
                # 途中でまた分断されてしまうため、必ずトークン単位で移動する。
                last_atom = current_atoms.pop()
                lines.append("".join(current_atoms))
                current_atoms = [last_atom, atom]
                current_str = last_atom + atom
            else:
                lines.append(current_str)
                current_atoms = [atom]
                current_str = atom
        else:
            current_atoms.append(atom)
            current_str = trial
    if current_str:
        lines.append(current_str)
    return lines


class _ReportPDF(FPDF):
    def __init__(self, font_path: str):
        super().__init__()
        if not os.path.exists(font_path):
            raise PdfExportError(
                f"日本語フォントが見つかりません: {font_path}\n"
                "IPAexゴシック(ipaexg.ttf)を fonts/ ディレクトリに配置してください。"
                "https://moji.or.jp/ipafont/ からダウンロードできます。"
            )
        self.add_font("ipaex", "", font_path, uni=True)
        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()

    def _max_line_width(self) -> float:
        # ぴったりの幅で折り返すと、フォント幅計算のわずかな誤差により
        # fpdf2のmulti_cell内部でさらに再折り返しされてしまうことがある
        # (行の途中で不自然に短く終わる原因になる)。安全マージンを設けて防ぐ。
        safety_margin = 1.5
        return self.w - self.l_margin - self.r_margin - safety_margin

    def _draw_lines(self, lines: list[str], line_height: float):
        # multi_cellに複数行をまとめて渡すと、fpdf2内部の幅計算とこちらの
        # 計算のごくわずかな誤差(浮動小数点の丸め等)により、既に幅内に
        # 収まっているはずの行が内部で再分割されてしまうことがある。
        # 1行ずつ確実に描画するため、折り返し済みの行はcell()で個別に描画する
        # (cellはmulti_cellと異なり、渡した文字列を自動で再折り返ししない)。
        for line in lines:
            self.cell(0, line_height, line, new_x="LMARGIN", new_y="NEXT", align="L")

    def write_heading(self, text: str, size: int = 14):
        self.set_font("ipaex", size=size)
        wrapped = _wrap_with_kinsoku(self, text, self._max_line_width())
        self._draw_lines(wrapped, 10)
        self.ln(2)

    def write_body(self, text: str, size: int = 11):
        self.set_font("ipaex", size=size)
        wrapped = _wrap_with_kinsoku(self, text, self._max_line_width())
        self._draw_lines(wrapped, 8)
        self.ln(1)


def _clean_line(text: str) -> str:
    """LLM出力に含まれがちな、このシンプルなレンダラーでは扱えない記法を正規化する。

    - **太字** / *斜体* / __太字__ などの強調記号を除去(このレンダラーは太字非対応のため)
    - 見た目を整えるためにLLMが挿入する連続空白(全角スペース含む)を1つに圧縮
      -> これを行わないと、単語の前後に不自然に大きな余白が生まれる
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"[ \t　]{2,}", " ", text)
    return text


def _needs_space_between(prev_char: str, next_char: str) -> bool:
    """行の結合時にスペースを入れるべきか判定する。

    日本語は単語間にスペースを入れない言語のため、単純に全結合箇所へ
    スペースを挿入すると「投資信 託」のように単語の途中に不自然な空きができる。
    一方で「eMAXIS Slim」のような英単語と日本語の境目にはスペースが必要。
    また「-60,000円」のような数値が改行で分断された場合(例: "-60," / "000円")に
    スペースを入れると数値の見た目が崩れるため、数字同士・数字と桁区切り記号の
    間にはスペースを入れない。
    """
    if prev_char.isdigit() and next_char.isdigit():
        return False
    if prev_char in ",." and next_char.isdigit():
        return False
    if prev_char.isascii() and prev_char.isalpha():
        return True
    if next_char.isascii() and next_char.isalpha():
        return True
    return False


def _parse_blocks(markdown_text: str) -> list[tuple[str, str]]:
    """Markdown文字列を(種別, テキスト)のブロック列に変換する。

    LLMは1つの文/箇条書き項目の途中で改行を入れるだけでなく、単語の途中で
    空行(改行2つ)まで挿入してくることがあるため、「空行=段落の区切り」という
    一般的なMarkdownの前提は採用しない。見出し(#)または新しい箇条書き(-/*)が
    現れるまでは、空行の有無に関わらずすべて同じブロックとして結合する。
    """
    blocks: list[tuple[str, str]] = []
    current_type: str | None = None
    current_parts: list[str] = []

    def flush():
        if not current_parts:
            return
        combined = current_parts[0]
        for part in current_parts[1:]:
            if combined and part and _needs_space_between(combined[-1], part[0]):
                combined += " " + part
            else:
                combined += part
        blocks.append((current_type or "para", combined.strip()))

    for raw_line in markdown_text.splitlines():
        line = _clean_line(raw_line)

        if not line.strip():
            # 空行はLLMが体裁のために挿入することが多いため、通常の段落では
            # 区切りとして扱わず無視する。ただし箇条書きの後の空行は、
            # 「リストの終わり」を示す一般的なMarkdownの合図として尊重し、
            # 後続の説明文が直前の箇条書き項目にくっつかないようにする。
            if current_type == "bullet":
                flush()
                current_parts.clear()
                current_type = None
            continue

        check_line = line.lstrip()  # 行頭空白のみ除去し、行末の空白(結合判定用)は残す

        heading_match = re.match(r"^(#{1,3})\s+(.*)", check_line)
        if heading_match:
            flush()
            current_parts.clear()
            level = len(heading_match.group(1))
            blocks.append((f"h{level}", heading_match.group(2).strip()))
            current_type = None
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)", check_line)
        if bullet_match:
            flush()
            current_parts.clear()
            current_type = "bullet"
            current_parts.append(bullet_match.group(1))
            continue

        # 見出し・新規箇条書きのいずれでもない -> 直前ブロックの続き
        if current_type is None:
            current_type = "para"
        current_parts.append(check_line)

    flush()
    return blocks


def _strip_leading_preamble(
    blocks: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """最初の見出しより前に来るブロックを取り除く。

    プロンプトで禁止していても、LLMが「以下にレポートを作成します」
    "Here is the report in Markdown format:" のような前置きの一言を
    付けてくることがある。実際のレポート内容は必ず見出しから始まる設計
    (report_engine.pyのプロンプト参照)のため、最初の見出しより前にある
    ブロックは前置きコメントとみなして除去する。
    """
    first_heading_index = next(
        (i for i, (block_type, _) in enumerate(blocks) if block_type.startswith("h")),
        None,
    )
    if first_heading_index:
        return blocks[first_heading_index:]
    return blocks


def markdown_to_pdf(
    markdown_text: str,
    output_path: str,
    title: str = "資産管理レポート",
    font_path: str = DEFAULT_FONT_PATH,
) -> str:
    """簡易的なMarkdown -> PDF変換。

    見出し(#, ##, ###)・箇条書き・段落を区別する簡易パーサー。
    表やリンクなど複雑なMarkdown記法までは対応しない(レポート用途で十分なため)。
    """
    pdf = _ReportPDF(font_path)
    pdf.write_heading(title, size=18)

    blocks = _parse_blocks(markdown_text)
    blocks = _strip_leading_preamble(blocks)
    # LLMが文章の先頭に独自のタイトル見出し(例: "# 資産管理レポート")を
    # つけてくることがあり、上で描画した固定タイトルと重複してしまうため、
    # 先頭ブロックが"レベル1"見出しの場合のみそちらを除去する。
    # (レベル2の "## 1. 保有資産の現状サマリー" のような、本来必要な
    #  セクション見出しまで誤って消さないよう、h1限定にしている)
    if blocks and blocks[0][0] == "h1":
        blocks = blocks[1:]

    heading_sizes = {"h1": 16, "h2": 14, "h3": 12}
    for block_type, text in blocks:
        if block_type in heading_sizes:
            pdf.write_heading(text, size=heading_sizes[block_type])
        elif block_type == "bullet":
            pdf.write_body("・" + text)
        else:
            pdf.write_body(text)

    pdf.output(output_path)
    return output_path
