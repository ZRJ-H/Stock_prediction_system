"""
新闻舆情 Skill（NewsSkill）
============================
获取股票近期新闻并进行舆情分析。

编排的工具：
  1. 获取新闻列表（腾讯/东方财富）
  2. 关键词提取（从标题和摘要中提取高频词）
  3. 情感倾向分析（正面/负面/中性计数）
  4. 综合舆情评级

输出：SkillReport（新闻列表 / 关键词 / 情感倾向 / 舆情评级）
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List

from core.news import NewsBundle, fetch_news
from core.market_data import get_realtime_quote
from core.skills.base import BaseSkill, ReportSection, SkillReport


# 正面/负面情感词库（简化版，不依赖额外NLP库）
_POSITIVE_WORDS = {
    "增持", "买入", "利好", "增长", "突破", "盈利", "分红", "回购", "中标",
    "业绩预增", "扭亏", "涨停", "创新高", "超预期", "改善", "扩张", "签约",
    "获批", "上市", "翻倍", "领涨", "龙头", "回购股份", "高增长",
    "利多", "看好", "跑赢", "优于", "强劲", "加速", "升级", "突破性",
}
_NEGATIVE_WORDS = {
    "减持", "卖出", "利空", "下跌", "亏损", "暴雷", "退市", "处罚", "罚款",
    "业绩预减", "跌停", "创新低", "低于预期", "恶化", "收缩", "违约", "诉讼",
    "调查", "警告", "停产", "裁员", "债务", "商誉减值", "质押", "冻结",
    "利淡", "看空", "跑输", "弱于", "疲软", "放缓", "下滑", "腰斩",
}


def _extract_keywords(texts: List[str], top_k: int = 8) -> List[str]:
    """从文本列表中提取高频关键词（简易TF，中文按字符2-gram切分）。"""
    all_words: List[str] = []
    for text in texts:
        # 提取中文连续字符段
        chinese_segs = re.findall(r"[一-鿿]{2,}", text)
        for seg in chinese_segs:
            # 2-gram 切分
            for i in range(len(seg) - 1):
                all_words.append(seg[i:i + 2])
    counter = Counter(all_words)
    # 过滤停用词
    stop = {"公司", "股份", "有限", "集团", "有限公", "限公司", "股票", "投资",
            "市场", "行情", "资金", "交易", "今日", "昨日", "本周", "本月",
            "显示", "同比", "数据", "证券", "基金", "板块", "行业", "相关",
            "一个", "这个", "什么", "可以", "进行"}
    for w in stop:
        counter.pop(w, None)
    return [w for w, _ in counter.most_common(top_k)]


def _sentiment_analysis(titles: List[str], summaries: List[str]) -> tuple:
    """简易情感分析：统计正面/负面词命中数。"""
    pos_count = 0
    neg_count = 0
    all_text = " ".join(titles + summaries)

    for w in _POSITIVE_WORDS:
        if w in all_text:
            pos_count += 1
    for w in _NEGATIVE_WORDS:
        if w in all_text:
            neg_count += 1

    total = pos_count + neg_count
    if total == 0:
        return "中性", 0, 0
    pos_ratio = pos_count / total
    if pos_ratio >= 0.65:
        return "偏正面", pos_count, neg_count
    elif pos_ratio >= 0.35:
        return "中性", pos_count, neg_count
    else:
        return "偏负面", pos_count, neg_count


class NewsSkill(BaseSkill):
    name = "news_sentiment"
    description = (
        "获取股票近期新闻并进行舆情分析，提取关键词、判断情感倾向、给出舆情评级。"
        "适用场景：用户询问新闻、消息、舆情、市场情绪。"
    )
    parameters = {
        "code": {"type": "string", "description": "6位数字股票代码"},
        "keyword": {"type": "string", "description": "可选：额外搜索关键词"},
    }

    def execute(self, code: str, keyword: str = "") -> SkillReport:
        q = get_realtime_quote(code) if code else None
        name = q.name if q else (code or keyword or "搜索")

        bundle: NewsBundle = fetch_news(code, keyword=keyword)
        sections: List[ReportSection] = []
        titles: List[str] = []
        summaries: List[str] = []

        if bundle.items:
            news_lines: List[str] = []
            for item in bundle.items:
                news_lines.append(item.to_line())
                titles.append(item.title)
                summaries.append(item.summary)

            sections.append(ReportSection(
                heading=f"近期新闻（来源：{bundle.source}）",
                content="\n\n".join(news_lines),
            ))

            # 关键词提取
            keywords = _extract_keywords(titles + summaries)
            sections.append(ReportSection(
                heading="高频关键词",
                content="  " + "、".join(keywords) if keywords else "  未能提取到关键主题词",
            ))

            # 情感分析
            sentiment, pos, neg = _sentiment_analysis(titles, summaries)
            sig = "bullish" if sentiment == "偏正面" else ("bearish" if sentiment == "偏负面" else "neutral")
            sections.append(ReportSection(
                heading="舆情情感分析",
                content=(
                    f"  情感倾向：{sentiment}\n"
                    f"  正面信号词命中：{pos}次\n"
                    f"  负面信号词命中：{neg}次\n"
                    f"  分析说明：基于内置情感词库的简化统计，仅供参考。"
                ),
                signal=sig,
            ))
        else:
            sections.append(ReportSection(
                heading="近期新闻",
                content=f"  暂无相关新闻数据。\n  来源：{bundle.source}",
            ))

        # 综合结论
        sentiment, _, _ = _sentiment_analysis(titles, summaries) if titles else ("中性", 0, 0)
        if sentiment == "偏正面":
            conclusion = "近期舆情偏正面，正面消息占优，市场情绪较乐观。"
        elif sentiment == "偏负面":
            conclusion = "近期舆情偏负面，需关注负面消息的实质影响和后续进展。"
        else:
            conclusion = "近期舆情中性，无明显的正面或负面偏向。注意甄别信息真伪。"

        return SkillReport(
            skill_name=self.name,
            title=f"{name} 新闻舆情分析",
            sections=sections,
            summary=conclusion,
        )
