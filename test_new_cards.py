#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新的正反面卡片生成功能
"""

from md_to_anki import MarkdownToAnki

def test_api_connection():
    """测试 API 连接"""
    print("=== 测试 API 连接 ===")
    converter = MarkdownToAnki()

    test_text = """
    ## 什么是算法？
    算法是解决问题的一系列明确步骤。它包含输入、处理和输出三个部分。
    """

    result = converter.call_llm_api("请用一句话解释什么是算法", max_tokens=100)
    if result:
        print(f"[OK] API 连接成功")
        print(f"返回内容: {result}")
    else:
        print("[FAIL] API 连接失败")
    print()

def test_card_generation():
    """测试卡片生成（带标签和 Extra）"""
    print("=== 测试增强版卡片生成 ===")
    converter = MarkdownToAnki()

    test_text = """
    ## 线性搜索
    线性搜索是一种简单的搜索算法，从数组的第一个元素开始，逐个检查每个元素，直到找到目标值或到达数组末尾。
    时间复杂度为 O(n)。

    适用场景：小规模数据、无序数组。
    """

    cards = converter.generate_cards_from_text(test_text, source_file="test.md")

    if cards:
        print(f"[OK] 成功生成 {len(cards)} 张卡片")
        for i, card in enumerate(cards, 1):
            print(f"\n卡片 {i}:")
            print(f"  正面: {card.get('front', 'N/A')}")
            print(f"  背面: {card.get('back', 'N/A')}")
            print(f"  补充: {card.get('extra', 'N/A')}")
            print(f"  来源: {card.get('source', 'N/A')}")
            print(f"  标签: {card.get('tags', [])}")
    else:
        print("[FAIL] 卡片生成失败")
    print()

if __name__ == "__main__":
    print("开始测试新的卡片生成功能\n")
    test_api_connection()
    test_card_generation()
    print("测试完成！")
