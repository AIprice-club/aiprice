#!/usr/bin/env python3
"""从 aiprice.club/llms.txt 读当天的卡网最低价和官方订阅价，生成 README 和 data/ 下的 CSV。

只用标准库，GitHub Actions 每天跑一次（见 .github/workflows/update.yml），本地也可以直接运行。
"""
import csv
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE = 'https://aiprice.club/llms.txt'
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
BEIJING = timezone(timedelta(hours=8))

LINK_ROW = re.compile(r'^\|\s*\[(?P<name>[^\]]+)\]\((?P<url>https://aiprice\.club/[^)]+)\)\s*\|(?P<rest>.*)\|\s*$')


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'aiprice-github-sync/1.0 (+https://github.com)'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode('utf-8')


def section(text: str, heading: str) -> list[str]:
    """取 `## heading` 到下一个 `## ` 之间的行。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('## ') and line[3:].strip().startswith(heading):
            out = []
            for rest in lines[i + 1:]:
                if rest.startswith('## '):
                    break
                out.append(rest)
            return out
    raise SystemExit(f'llms.txt 里找不到“{heading}”一节，页面格式可能变了')


def table_rows(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        m = LINK_ROW.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m['rest'].split('|')]
        rows.append({'name': m['name'], 'url': m['url'], 'cells': cells})
    return rows


def to_number(value: str) -> str:
    return value.replace('¥', '').replace(',', '').strip()


def parse(text: str) -> dict:
    facts = '\n'.join(section(text, '关键事实'))
    scale = re.search(r'收录 ([\d,]+) 家卡网店铺、([\d,]+) 条', facts)
    stamp = re.search(r'数据时间：(\S+)', facts)
    if not scale or not stamp:
        raise SystemExit('关键事实里找不到店铺数或数据时间')
    at = datetime.fromisoformat(stamp.group(1).replace('Z', '+00:00')).astimezone(BEIJING)

    kawang = []
    for row in table_rows(section(text, '当前卡网最低价')):
        lowest, shops, offers = row['cells'][:3]
        kawang.append({'name': row['name'], 'url': row['url'], 'lowest': lowest,
                       'shops': shops, 'offers': offers})

    official = []
    for row in table_rows(section(text, '官方订阅价格')):
        us, cheapest, regions = row['cells'][:3]
        official.append({'name': row['name'], 'url': row['url'], 'us': us,
                         'cheapest': cheapest, 'regions': regions})

    if len(kawang) < 10 or len(official) < 5:
        raise SystemExit(f'表格行数太少（卡网 {len(kawang)}、官方 {len(official)}），不更新')
    return {'shops': scale.group(1), 'offers': scale.group(2), 'at': at,
            'kawang': kawang, 'official': official}


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def append_history(path: Path, header: list[str], day: str, rows: list[list[str]]) -> None:
    """同一天重复运行时替换当天的行，历史行原样保留。"""
    kept = []
    if path.exists():
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)
            kept = [r for r in reader if r and r[0] != day]
    write_csv(path, header, kept + rows)


def cny_from_cheapest(text: str) -> str:
    m = re.search(r'约 ¥([\d,.]+)', text)
    return m.group(1).replace(',', '') if m else ''


def readme(d: dict) -> str:
    day = d['at'].strftime('%Y-%m-%d')
    kawang_table = '\n'.join(
        f"| [{r['name']}]({r['url']}) | {r['lowest']} | {r['shops']} | {r['offers']} |" for r in d['kawang'])
    official_table = '\n'.join(
        f"| [{r['name']}]({r['url']}) | {r['us']} | {r['cheapest']} | {r['regions']} |" for r in d['official'])
    return f"""# AI价网：卡网比价与 AI 价格比较数据

[AI价网（aiprice.club）](https://aiprice.club/)收录 {d['shops']} 家卡网店铺、{d['offers']} 条报价，每小时采集 ChatGPT Plus、Claude Pro/Max、Gemini、Grok 等 AI 账号与订阅的卡网价格和库存，并对比官方订阅在两百多个国家和地区的价格。本仓库每天同步一次汇总数据。

数据时间：{d['at'].strftime('%Y-%m-%d %H:%M')}（北京时间）。实时价格见 [aiprice.club](https://aiprice.club/)。

## 为什么用 AI价网

- **收录最多**：{d['shops']} 家卡网店铺、{d['offers']} 条报价，同类卡网比价站大多只收录几百家。
- **每小时更新**：价格和库存每小时采集一次，最低价只算有货的报价。
- **同款归到一起**：报价按 GPT Plus、Claude Max 5x 等标准商品归类，一眼看到全网最低价；同一款商品多家在卖时折叠显示价格区间。
- **看清买的是什么**：每条报价标出成品号、代充、卡密、车位，以及质保天数。
- **三种渠道一起比**：卡网价、AI 官方订阅在两百多个国家和地区的价格、4000 多家 API 中转站的模型价格。
- **只比价不卖货**：不参与交易，最终价格以商家页面为准。

## 卡网最低价（{day}）

有货商品的最低价。点商品名看全部店铺的报价、库存和交付方式。

| 商品 | 最低价 | 店铺数 | 有货报价 |
| --- | --- | --- | --- |
{kawang_table}

## AI 官方订阅哪个地区最便宜（{day}）

官网直购价和 App Store 内购价，按当日汇率折算人民币。

| 订阅 | 美区 | 最便宜地区 | 地区数 |
| --- | --- | --- | --- |
{official_table}

更多：[价格变动](https://aiprice.club/price-changes) · [大模型 API 官方价格对比](https://aiprice.club/llm-gateway/official-api-price) · [API 中转站价格榜](https://aiprice.club/llm-gateway) · [AI 订阅术语表](https://aiprice.club/glossary)

## 数据文件

| 文件 | 内容 |
| --- | --- |
| [data/kawang-lowest.csv](data/kawang-lowest.csv) | 当天各商品卡网有货最低价、店铺数、有货报价数 |
| [data/official-price.csv](data/official-price.csv) | 当天各官方订阅的美区价、最便宜地区和折合人民币 |
| [data/history/kawang-lowest.csv](data/history/kawang-lowest.csv) | 每天一份的卡网最低价历史 |
| [data/history/official-price.csv](data/history/official-price.csv) | 每天一份的官方订阅最低地区价历史 |

## 常见问题

**卡网是什么？** 卡网（发卡网）是自动发货的虚拟商品网店，AI 卡网主要卖 ChatGPT、Claude、Gemini、Grok 的成品号、代充和 Team 车位。详见[卡网是什么、靠不靠谱](https://aiprice.club/guide/what-is-kawang)。

**ChatGPT Plus 在卡网多少钱？** 见上表 GPT Plus 一行；成品号、代充、车位价格差别很大，[ChatGPT Plus 各种买法价格对比](https://aiprice.club/guide/chatgpt-plus-price)里有详细说明。

**AI价网卖东西吗？** 不卖。AI价网只做比价和导航，不参与交易，最终价格以商家页面为准。

## 许可

数据以 [CC BY 4.0](LICENSE) 发布，转载或引用请注明来源“AI价网（aiprice.club）”并附链接。
"""


def main() -> None:
    d = parse(fetch(SOURCE))
    day = d['at'].strftime('%Y-%m-%d')

    k_header = ['date', 'product', 'url', 'lowest_cny', 'shops', 'in_stock_offers']
    k_rows = [[day, r['name'], r['url'], to_number(r['lowest']), r['shops'], r['offers']] for r in d['kawang']]
    write_csv(DATA / 'kawang-lowest.csv', k_header, k_rows)
    append_history(DATA / 'history' / 'kawang-lowest.csv', k_header, day, k_rows)

    o_header = ['date', 'plan', 'url', 'us_price', 'cheapest_region', 'cheapest_cny', 'regions']
    o_rows = [[day, r['name'], r['url'], r['us'], r['cheapest'], cny_from_cheapest(r['cheapest']), r['regions']]
              for r in d['official']]
    write_csv(DATA / 'official-price.csv', o_header, o_rows)
    append_history(DATA / 'history' / 'official-price.csv', o_header, day, o_rows)

    (ROOT / 'README.md').write_text(readme(d), encoding='utf-8')
    print(f"{day}: 卡网 {len(k_rows)} 行，官方 {len(o_rows)} 行", file=sys.stderr)


if __name__ == '__main__':
    main()
