"""Rule-based text normalization before the tokenizer (the model itself takes the raw text).

Why: spaces become their own tokens (odd pauses), Arabic digits next to hanzi get odd pauses / readings ("1银"), and a
sentence without final punctuation tends to end early (last syllable swallowed).

All languages: collapse whitespace, add final punctuation if missing.
Chinese (incl. the dialect speakers): full-width digits -> ASCII, remove spaces around hanzi / digits, then numbers:
  thousands separators 1,250 -> 1250, dates 2024-03-15 / 2024/3/15 -> 二零二四年三月十五日,
  units after a number (5000mAh -> 五千毫安时, 23.4km, 29μg/m³ -> 二十九微克每立方米, -5℃ -> 零下五摄氏度),
  fractions 1/4 -> 四分之一, percent 12.5% -> 百分之十二点五, time 9:05 -> 九点零五分 (H:MM with H <= 23, MM <= 59),
  ratios / scores 3:2 -> 三比二, 7.5:41.2:51.3 -> 七点五比四十一点二比五十一点三, year 2023年 -> 二零二三年 (4 digits;
  10年 / 30年 are durations -> 十年 / 三十年), range 3-5 -> 三到五, decimal 3.14 -> 三点一四, negative -3 -> 负三;
  digit by digit: a leading 0 (0203), > 12 digits, mobile numbers (1[3-9] + 9 digits), room / bed numbers (307床),
  or after 电话/热线/号码/编号/尾号/卡号/账号/QQ; other integers as cardinals (2 before a measure word -> 两,
  2000 -> 两千), 3金1银 -> 三金一银.
"""
import re

DIG = "零一二三四五六七八九"
CJK = r"一-鿿㐀-䶿"
END = "。！？!?…；;.~"
MEASURE = ("个只位本条张次件名人块元岁天年月周小时分钟秒米公里斤克台辆家所种项场局枚金银铜届倍层口双对套")


def _digits(s):
    return "".join(DIG[int(c)] for c in s)


def _section(n):                                     # 0 < n < 10000
    out, zero = "", False
    for unit, v in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
        d = n // v % 10
        if d:
            if zero:
                out += "零"
            out += DIG[d] + unit
            zero = False
        elif out:
            zero = True
    return out


def cardinal(n):
    """non-negative integer -> Chinese reading (万 / 亿 grouping, 十五 not 一十五)"""
    if n == 0:
        return "零"
    parts, units, i = [], ["", "万", "亿", "万亿"], 0
    while n and i < len(units):
        n, sec = divmod(n, 10000)
        parts.append((sec, units[i]))
        i += 1
    out, need_zero = "", False
    for sec, unit in reversed(parts):
        if sec == 0:
            need_zero = bool(out)
            continue
        if out and (need_zero or sec < 1000):
            out += "零"
        out += _section(sec) + unit
        need_zero = False
    return out[1:] if out.startswith("一十") else out


CODE_CTX = re.compile(r"(电话|热线|手机|号码|编号|尾号|卡号|账号|工号|学号|车牌|邮编|验证码|QQ|qq|微信)[^，。！？；]{0,6}$")
ROOM_NEXT = re.compile(r"(床|房间|号房|病房|室)")             # 307床, 1203房间: read digit by digit when >= 3 digits
# units after a number (longest first); the Latin ones only when not followed by another letter
UNITS = [("μg/m³", "微克每立方米"), ("mg/m³", "毫克每立方米"), ("km/h", "公里每小时"), ("m/s", "米每秒"),
         ("mAh", "毫安时"), ("kWh", "千瓦时"), ("kW", "千瓦"), ("GHz", "吉赫兹"), ("MHz", "兆赫兹"), ("Hz", "赫兹"),
         ("km²", "平方公里"), ("m²", "平方米"), ("m³", "立方米"), ("cm", "厘米"), ("mm", "毫米"), ("km", "公里"),
         ("kg", "千克"), ("mg", "毫克"), ("ml", "毫升"), ("mL", "毫升"), ("°C", "摄氏度"), ("℃", "摄氏度"),
         ("°", "度")]
UNIT_RE = re.compile(r"(\d)\s*(" + "|".join(re.escape(u) for u, _ in UNITS) + r")(?![A-Za-z])")
UNIT_MAP = dict(UNITS)


def _int(s, nxt="", before=""):
    if ((len(s) > 1 and s[0] == "0") or len(s) > 12 or CODE_CTX.search(before) or re.fullmatch(r"1[3-9]\d{9}", s)
            or (len(s) >= 3 and ROOM_NEXT.match(nxt))):
        return _digits(s)                            # phone numbers, ids, codes, room / bed numbers
    if s == "2" and nxt and nxt[0] in MEASURE:
        return "两"
    r = cardinal(int(s))
    return "两" + r[1:] if r[:2] in ("二千", "二万", "二亿") else r


def normalize_zh(t):
    t = t.translate({0xFF10 + i: 0x30 + i for i in range(10)})          # full-width digits
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(rf"(?<=[{CJK}\d，。！？、；：])\s+", "", t)
    t = re.sub(rf"\s+(?=[{CJK}\d，。！？、；：])", "", t)
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)                     # thousands separators 1,250,000
    t = re.sub(r"(?<![\d.])(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?![\d.])",          # dates 2024-03-15
               lambda m: (_digits(m.group(1)) + "年" + cardinal(int(m.group(2))) + "月"
                          + cardinal(int(m.group(3))) + "日"), t)
    t = UNIT_RE.sub(lambda m: m.group(1) + UNIT_MAP[m.group(2)], t)
    t = re.sub(r"(?<![\d.])-\s*(?=\d+(?:\.\d+)?摄氏度)", "零下", t)        # -5℃
    t = re.sub(r"(?<![\d./])(\d{1,3})/(\d{1,3})(?![\d/])", lambda m: _int(m.group(2)) + "分之" + _int(m.group(1)), t)
    t = re.sub(r"/", "每", t)                                            # 元/斤, 次/秒
    t = re.sub(r"(\d+(?:\.\d+)?)\s*[%％]", lambda m: "百分之" + _num(m.group(1)), t)
    t = re.sub(r"(?<![\d.:：])(\d+(?:\.\d+)?)((?:[:：]\d+(?:\.\d+)?)+)(?![\d.:：])", _colon, t)
    t = re.sub(r"(?<!\d)(\d{4})年", lambda m: _digits(m.group(1)) + "年", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*[-~～—]\s*(\d+(?:\.\d+)?)", lambda m: _num(m.group(1)) + "到" + _num(m.group(2)), t)
    t = re.sub(r"(?<![0-9A-Za-z.])-(?=\d)", "负", t)                        # other negatives (not 3-5, not A-1)
    t = re.sub(r"\d+\.\d+", lambda m: _num(m.group(0)), t)
    t = re.sub(r"\d+", lambda m: _int(m.group(0), t[m.end():m.end() + 2], t[max(0, m.start() - 12):m.start()]), t)
    return t


def _colon(m):
    """9:05 -> time (one colon, H <= 23, two-digit MM <= 59); otherwise a ratio / score: 3:2, 7.5:41.2:51.3 -> 比"""
    parts = [m.group(1)] + re.split(r"[:：]", m.group(2))[1:]
    if len(parts) == 2 and "." not in m.group(0) and int(parts[0]) <= 23 and len(parts[1]) == 2 and int(parts[1]) <= 59:
        h, mm = int(parts[0]), parts[1]
        if mm == "00":
            return cardinal(h) + "点"
        return cardinal(h) + "点" + ("零" + DIG[int(mm)] if mm[0] == "0" else cardinal(int(mm))) + "分"
    return "比".join(_num(x) for x in parts)


def _num(s):
    if "." in s:
        a, b = s.split(".", 1)
        return cardinal(int(a)) + "点" + _digits(b)
    return _int(s)


def normalize(text, language="chinese"):
    t = re.sub(r"\s+", " ", str(text)).strip()
    if not t:
        return t
    if language.lower() in ("chinese", "beijing_dialect", "sichuan_dialect"):
        t = normalize_zh(t)
        if t[-1] not in END + "：:”’」』）)":                      # 亲爱的小雨： keeps its colon
            t += "。"
    elif t[-1] not in END + "\"')”’」』）》】»":                   # a closing quote / bracket ends it too
        t += "。" if language.lower() == "japanese" else "."
    return t


if __name__ == "__main__":
    for s in ["从本届亚运会来看，林诗栋夺得 3 金 1 银", "从本届亚运会来看，林诗栋夺得3金1银", "从本届亚运会来看，林诗栋夺得三金一银",
              "2023年增长了12.5%，共有2个人参加", "会议定在9:05，电话13812345678，房间号0203", "价格在3-5元之间，共10086人",
              "第100001位，约20000000人，1010次，2000元", "手机尾号是8765，邮编100080", "The price is 3 dollars",
              "将近30年，那是10年前的事，时隔12年", "电池5000mAh，全长23.4km，浓度29μg/m³，气温-5℃，油温150～180℃",
              "缩小到1/4甚至1/8，价格3元/斤", "307床的周阿姨，住在1203房间，第3号线", "结构为7.5:41.2:51.3，以3:2获胜，5:30起床，23:59",
              "游客1,250万人次，收入1,234,567元", "2024-03-15发布，2024/3/5截止", "热线12345，报警电话110，手机13812345678",
              "温差-3到5度，账户余额-200元", "2个人，22个人，2斤，2.5元"]:
        print(s, "->", normalize(s, "chinese" if re.search(f"[{CJK}]", s) else "english"))
