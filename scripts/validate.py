#!/usr/bin/env python3
"""validate.py — ai-chain-embed AI 全链路嵌入计划七维校验器

输入: AI 全链路嵌入计划 JSON（schema 见 tests/sample_good.json）
  {
    "level": {
      "current": "process",          // tool | process | chain（当前级别）
      "target": "chain",             // tool | process | chain（目标级别）
      "gap_reason": "节点间人肉传递，无回流"   // 非空：为什么没到目标级
    },
    "nodes": [
      {"name": "选品", "ai_duty": "跑容量/集中度/价格带", "human_duty": "拍板做/不做，输出清单"},
      {"name": "内容", "ai_duty": "listing初稿", "human_duty": "语气校准+合规审查"},
      {"name": "投放", "ai_duty": "结构分组/否定词清理", "human_duty": "预算分配+止损线"},
      {"name": "客服", "ai_duty": "常见问答模板化", "human_duty": "升级投诉+评价危机"}
    ],
    "alignment": {
      "upstream_is_downstream_input": true,   // 上游输出=下游输入
      "feedback_paths": ["投放数据回流选品", "客服高频问题回流内容"],  // 非空：≥1 条回流
      "breakpoints": []                       // 已识别断点（须为空或已排期修复）
    },
    "goal": {
      "metric": "单店月运营工时",
      "baseline": 240,                         // 基线数字 >0
      "target": 168,                           // 目标数字 >0 且 < baseline（降本方向）
      "headline_kpi_from_benchmark": false     // 不得拿头部公司数字直接当 KPI
    },
    "rhythm": {
      "has_backward_plan": true,               // 有倒推时间表（非临场反应）
      "node_check_items": [                    // 每节点一个检查项，非空
        {"node": "T-60备货", "check_item": "库存深度vs预测流量，缺口>20%启动补货"},
        {"node": "T-30预热", "check_item": "预热期ACOS基线已记录"},
        {"node": "T-7锁仓", "check_item": "到仓时间vs大促开始时间缓冲≥3天"}
      ]
    },
    "landing": {
      "sop_within_72h": true,                  // 72 小时内改 ≥1 条 SOP
      "sop_written_into_doc": true,            // 写进流程文档（不是会议纪要）
      "trial_period_days": 14,                 // 跑 N 天看数据（>0）
      "sops_written": 1                        // 改了几条 SOP（≥1）
    },
    "data_provenance": [
      {"claim": "营收24.51亿/净利+80.92%", "source": "financial_report", "used_for": "direction"},
      {"claim": "爆款预测准确率82%", "source": "self_report", "used_for": "direction"},
      {"claim": "运营效率提升60%", "source": "self_report", "used_for": "hypothesis"}
    ]
  }

七维校验（任一 FAIL → exit 1）：
  D1 级别判定: current/target ∈ {tool, process, chain} 且 current≠target
     （有升级意图）且 gap_reason 非空；current=chain 且 target=chain 且
     gap_reason 空 = 无升级意图的伪计划
  D2 四节点 AI/人配对: nodes 非空；每节点 ai_duty 与 human_duty 均非空；
     human_duty 不得含"无/暂无/待定"（人侧空 = 单点提效冒充链路）
  D3 链路对齐: upstream_is_downstream_input=true 且 feedback_paths 非空
     且 breakpoints 为空（有断点 = 链路没通，禁止宣称全链路）
  D4 可量化目标: metric 非空 且 baseline>0 且 target>0 且 target<baseline
     （降本方向）且 headline_kpi_from_benchmark=false（拿头部数字当 KPI=拦截）
  D5 倒推时间表: has_backward_plan=true 且 node_check_items 非空且每项
     node/check_item 均非空（临场反应不是方案；节点无检查项 = 节奏会打架）
  D6 72 小时落地: sop_within_72h=true 且 sop_written_into_doc=true 且
     trial_period_days>0 且 sops_written≥1（没写进流程文档 = 没落地）
  D7 数据溯源: data_provenance 非空；每项 source ∈
     {financial_report, self_report, expectation}；used_for ∈
     {direction, hypothesis} —— self_report/expectation 的 used_for 不得为
     "kpi"（自述与预期不得直接进决策数字/KPI）

退出码：0=通过 / 1=有缺陷 / 2=文件/格式错误
"""
import json
import sys

LEVELS = {"tool", "process", "chain"}
SOURCES = {"financial_report", "self_report", "expectation"}
USED_FOR = {"direction", "hypothesis", "kpi"}
HUMAN_DUTY_VOID = ("无", "暂无", "待定", "none")


def fail(checks, code, msg):
    checks.append(("FAIL", code, msg))


def ok(checks, code, msg):
    checks.append(("OK", code, msg))


def is_nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def validate(plan):
    checks = []

    # D1 级别判定
    lv = plan.get("level") or {}
    cur, tgt = lv.get("current"), lv.get("target")
    if cur not in LEVELS or tgt not in LEVELS:
        fail(checks, "D1", f"current={cur!r}/target={tgt!r} 非法——级别须 tool/process/chain")
    elif cur == tgt and not is_nonempty_str(lv.get("gap_reason")):
        fail(checks, "D1", f"current=target={cur} 且无差距说明——没有升级意图的伪计划")
    elif not is_nonempty_str(lv.get("gap_reason")):
        fail(checks, "D1", "gap_reason 为空——没答清卡在哪（如'AI 用了但没形成流程'）")
    else:
        ok(checks, "D1", f"级别判定清晰（{cur} → {tgt}，差距: {lv['gap_reason']}）")

    # D2 四节点 AI/人配对
    nodes = plan.get("nodes") or []
    if not nodes:
        fail(checks, "D2", "nodes 为空——没有四节点嵌入设计")
    else:
        bad_nodes = []
        for n in nodes:
            nm = n.get("name", "?")
            if not is_nonempty_str(n.get("ai_duty")):
                bad_nodes.append(f"{nm}(ai_duty 空)")
            hd = n.get("human_duty")
            if not is_nonempty_str(hd):
                bad_nodes.append(f"{nm}(human_duty 空=单点提效冒充链路)")
            elif any(w in hd for w in HUMAN_DUTY_VOID):
                bad_nodes.append(f"{nm}(human_duty='{hd}'=人侧没认领)")
        if bad_nodes:
            fail(checks, "D2", "AI/人配对缺: " + "；".join(bad_nodes))
        else:
            ok(checks, "D2", f"{len(nodes)} 个节点均含 AI/人不可让渡配对")

    # D3 链路对齐
    al = plan.get("alignment") or {}
    bps = al.get("breakpoints") or []
    if al.get("upstream_is_downstream_input") is not True:
        fail(checks, "D3", "upstream_is_downstream_input=false——上游输出≠下游输入，链路没通")
    elif not any(is_nonempty_str(x) for x in al.get("feedback_paths") or []):
        fail(checks, "D3", "feedback_paths 为空——没有数据回流路径，四个单点拼在一起")
    elif bps:
        fail(checks, "D3", f"已识别断点未修复: {bps}——有断点禁止宣称全链路")
    else:
        ok(checks, "D3", f"链路对齐（{len(al.get('feedback_paths') or [])} 条回流路径，无未修复断点）")

    # D4 可量化目标
    gl = plan.get("goal") or {}
    base, tgt = gl.get("baseline"), gl.get("target")
    if not is_nonempty_str(gl.get("metric")):
        fail(checks, "D4", "metric 为空——没数字的提效目标不是目标")
    elif not isinstance(base, (int, float)) or base <= 0:
        fail(checks, "D4", f"baseline={base!r}——先量基线（现在人工做这些要多久）再定目标")
    elif not isinstance(tgt, (int, float)) or tgt <= 0 or tgt >= base:
        fail(checks, "D4", f"target={tgt!r}——降本方向须 0 < target < baseline")
    elif gl.get("headline_kpi_from_benchmark") is not False:
        fail(checks, "D4", "headline_kpi_from_benchmark=true——拿头部公司数字直接当 KPI，样本单一不可比")
    else:
        pct = round((1 - tgt / base) * 100)
        ok(checks, "D4", f"目标可量化（{gl['metric']}: {base}→{tgt}, -{pct}%，非头部 KPI 直搬）")

    # D5 倒推时间表
    rh = plan.get("rhythm") or {}
    items = rh.get("node_check_items") or []
    if rh.get("has_backward_plan") is not True:
        fail(checks, "D5", "has_backward_plan=false——临场反应式备战不是方案，须倒推排表")
    elif not items:
        fail(checks, "D5", "node_check_items 为空——周期节点没检查项，节奏会互相打架")
    else:
        bad_items = [it.get("node", "?") for it in items
                     if not is_nonempty_str(it.get("node")) or not is_nonempty_str(it.get("check_item"))]
        if bad_items:
            fail(checks, "D5", f"检查项不全: {bad_items}——每节点必须有一个检查项")
        else:
            ok(checks, "D5", f"倒推时间表（{len(items)} 个节点各带检查项）")

    # D6 72 小时落地
    ld = plan.get("landing") or {}
    if ld.get("sop_within_72h") is not True:
        fail(checks, "D6", "sop_within_72h=false——72 小时外的'回头再弄'=没落地")
    elif ld.get("sop_written_into_doc") is not True:
        fail(checks, "D6", "sop_written_into_doc=false——没写进流程文档（留在会议纪要里）=没落地")
    else:
        tp, sw = ld.get("trial_period_days"), ld.get("sops_written")
        if not isinstance(tp, int) or tp <= 0:
            fail(checks, "D6", f"trial_period_days={tp!r}——须跑 ≥1 天看数据")
        elif not isinstance(sw, int) or sw < 1:
            fail(checks, "D6", f"sops_written={sw!r}——至少改 1 条 SOP，参会价值在于改了几条流程")
        else:
            ok(checks, "D6", f"72 小时落地（{sw} 条 SOP 进流程文档，跑 {tp} 天看数据）")

    # D7 数据溯源
    dp = plan.get("data_provenance") or []
    if not dp:
        fail(checks, "D7", "data_provenance 为空——引用数字不标来源类型，转述链会放大错误")
    else:
        bad_dp = []
        for d in dp:
            c = d.get("claim", "?")
            if d.get("source") not in SOURCES:
                bad_dp.append(f"「{c}」source 非法（须 financial_report/self_report/expectation）")
            elif d.get("used_for") not in USED_FOR:
                bad_dp.append(f"「{c}」used_for 非法（须 direction/hypothesis/kpi）")
            elif d.get("source") in ("self_report", "expectation") and d.get("used_for") == "kpi":
                bad_dp.append(f"「{c}」自述/预期直接当 KPI——只做方向判断与假设，不签 KPI")
        if bad_dp:
            fail(checks, "D7", "数据溯源: " + "；".join(bad_dp))
        else:
            ok(checks, "D7", f"{len(dp)} 条数字均标注来源且用途合规")

    return checks


def main():
    if len(sys.argv) != 2:
        print("usage: python validate.py plan.json", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取/解析: {e}", file=sys.stderr)
        return 2
    if not isinstance(plan, dict):
        print("ERROR: 顶层必须是 JSON 对象", file=sys.stderr)
        return 2

    checks = validate(plan)
    fails = [c for c in checks if c[0] == "FAIL"]
    for status, code, msg in checks:
        if status == "FAIL":
            print(f"[{code}] FAIL {msg}")
    print(f"== {len(checks) - len(fails)} OK / {len(fails)} FAIL ==")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
