// 数桥 DataBridge · 17 页答辩 PPTX 生成器（PptxGenJS，原生可编辑）
// 运行：node scripts/build_pptx.mjs
// 依赖安装在 outputs/_pptx（gitignore）：npm --prefix outputs/_pptx install pptxgenjs
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(ROOT, 'outputs/_pptx/node_modules/'));
const PptxGenJS = require('pptxgenjs');

// ---------- 设计令牌（沿用 答辩幻灯片.html 身份：白底深蓝、红涨绿跌） ----------
const C = {
  ink: '0D1B32', ink2: '3A475F', ink3: '69768F', line: 'DDE4EE',
  navy: '142C55', navy2: '1D4686', blue: '2F5FD0', blueSoft: 'EAF0FE',
  up: 'C62828', upBg: 'FDECEC', upLine: 'E6B9B9',
  down: '1C7A44', downBg: 'EBF6EF', downLine: 'AED6BD',
  warn: 'A96608', warnBg: 'FFF6E1', card: 'FBFCFE', panel: 'F3F7FF',
  dark: '0C1730', dark2: '0E2148', white: 'FFFFFF',
};
const F = 'Microsoft YaHei';   // 中文正文（目标环境 Windows 必有）
const FN = 'Arial';            // 短数字/编号，度量稳定
const MONO = 'Consolas';

const pres = new PptxGenJS();
pres.defineLayout({ name: 'WIDE', width: 13.333, height: 7.5 });
pres.layout = 'WIDE';
pres.author = '数桥 DataBridge 团队';
pres.company = '华东师范大学 · 数联科技 AI 智能体校园黑客松';
pres.subject = '赛题二 · 面向 AI Agent 的可信取数平台';
pres.title = '数桥 DataBridge · 答辩（17 页）';

const ML = 0.62, MR = 0.62, CW = 13.333 - ML - MR; // 12.09
const RR = 'roundRect', RC = 'rect', EL = 'ellipse';
const noLine = { type: 'none' };

// ---------- 原语 ----------
function base(dark = false) {
  const s = pres.addSlide();
  s.background = { color: dark ? C.dark2 : C.white };
  return s;
}
function T(s, text, o = {}) {
  s.addText(text, { fontFace: o.num ? FN : F, fontSize: 12, color: C.ink, margin: 0,
    h: 0.38, ...o });
}
function chrome(s, cap, crumb, folio, dark = false) {
  const capFill = dark ? { color: C.white, transparency: 86 } : { color: C.blue };
  const capLine = dark ? { color: C.white, transparency: 68, pt: 1 } : noLine;
  s.addShape(RR, { x: ML, y: 0.40, w: 3.3, h: 0.32, rectRadius: 0.05, fill: capFill, line: capLine });
  T(s, cap, { x: ML, y: 0.40, w: 3.3, h: 0.32, align: 'center', valign: 'middle',
    fontSize: 10, bold: true, color: dark ? C.white : C.white, charSpacing: 0.5 });
  s.addShape(RC, { x: ML + 3.46, y: 0.555, w: 6.2, h: 0.022, fill: { color: dark ? C.white : C.blue, transparency: dark ? 55 : 0 } });
  T(s, crumb, { x: 9.72, y: 0.40, w: 2.62, h: 0.32, align: 'right', valign: 'middle',
    fontSize: 10, color: dark ? 'AEC6E8' : C.ink3 });
  // 极淡水印，避开右上路径文字的视觉冲突
  T(s, folio, { x: 11.45, y: -0.04, w: 1.5, h: 1.0, align: 'right', valign: 'top',
    fontFace: FN, fontSize: 54, bold: true, color: dark ? 'FFFFFF' : 'F2F6FC', transparency: dark ? 93 : 0,
    margin: 0, wrap: false, num: true });
}
function title(s, t, o = {}) {
  T(s, t, { x: ML, y: 1.02, w: CW, h: 0.72, fontSize: o.size || 25, bold: true, color: o.color || C.navy,
    align: o.align || 'left' });
}
function footer(s, left, src, dark = false) {
  s.addShape(RC, { x: ML, y: 6.94, w: CW, h: 0.012, fill: { color: dark ? C.white : C.line, transparency: dark ? 70 : 0 } });
  T(s, left, { x: ML, y: 7.02, w: 9.4, h: 0.3, fontSize: 10, color: dark ? '9FB6DD' : C.ink3, valign: 'middle' });
  if (src) T(s, src, { x: 10.1, y: 7.02, w: 2.61, h: 0.3, fontSize: 9.5, color: dark ? '7E93BD' : '8A96AC', align: 'right', valign: 'middle', fontFace: MONO });
}
function panel(s, x, y, w, h, o = {}) {
  s.addShape(RR, { x, y, w, h, rectRadius: 0.09, fill: { color: o.fill || C.card },
    line: { color: o.line || C.line, pt: 1 },
    // 必须每个形状一个新阴影对象：pptxgenjs 会就地归一化 shadow，复用引用会跨形状累乘
    shadow: o.shadow ? { type: 'outer', color: '0D1B32', opacity: 0.12 } : undefined });
}
function cardHead(s, x, y, ico, text, color = C.blue, cw = 3.5) {
  const bg = color === C.up ? C.upBg : C.blueSoft;
  s.addShape(RR, { x, y: y + 0.01, w: 0.34, h: 0.34, rectRadius: 0.06, fill: { color: bg } });
  T(s, ico, { x, y: y + 0.01, w: 0.34, h: 0.34, align: 'center', valign: 'middle', fontSize: 13, color, bold: true });
  T(s, text, { x: x + 0.44, y, w: cw - 0.62, h: 0.37, fontSize: 14.5, bold: true, color: C.navy });
}
function bullets(s, items, x, y, w, h, o = {}) {
  const runs = [];
  items.forEach((it, i) => runs.push({ text: it, options: {
    bullet: { type: 'ul', indent: 12, hanging: 3 }, breakLine: i < items.length - 1,
    paraSpaceAfter: o.after == null ? 7 : o.after } }));
  s.addText(runs, { x, y, w, h, fontFace: F, fontSize: o.fs || 12, color: o.color || C.ink2,
    margin: 0, valign: 'top', lineSpacingMultiple: 1.08 });
}
function chip(s, x, y, w, text, o = {}) {
  s.addShape(RR, { x, y, w, h: o.h || 0.34, rectRadius: 0.17,
    fill: o.transparency == null ? { color: o.bg || C.blueSoft } : { color: o.bg || C.white, transparency: o.transparency },
    line: { color: o.line || 'CBD9F7', pt: 1, transparency: o.lineTransparency || 0 } });
  T(s, text, { x, y, w, h: o.h || 0.34, align: 'center', valign: 'middle', fontSize: o.fs || 11,
    bold: true, color: o.color || C.navy, margin: 0.02, fit: 'shrink' });
}
function stat(s, x, y, w, h, k, v, o = {}) {
  panel(s, x, y, w, h, { fill: o.fill || C.card, line: o.line || C.line });
  T(s, k, { x: x + 0.14, y: y + 0.11, w: w - 0.28, h: 0.26, fontSize: 10.5, color: o.kColor || C.ink3 });
  T(s, v, { x: x + 0.14, y: y + 0.39, w: w - 0.28, h: h - 0.5, fontSize: o.fs || 21, bold: true,
    color: o.vColor || C.navy, num: true, margin: 0, fit: 'shrink' });
}
function note(s, text) { s.addNotes(text); }

function makeTable(s, headers, rows, x, y, colW, o = {}) {
  const fs = o.fs || 11, padL = 8, hh = o.hh || 0.40, rh = o.rh || 0.47;
  const head = headers.map((hd) => ({ text: hd, options: { bold: true, color: C.ink3, fontSize: fs - 0.5,
    fill: { color: 'F3F7FC' }, margin: [3, padL, 3, padL], valign: 'middle', fontFace: F } }));
  const body = rows.map((r) => r.map((c) => {
    const cell = typeof c === 'string' ? { t: c } : c;
    return { text: cell.t, options: {
      color: cell.color || C.ink2, bold: !!cell.bold, fontSize: cell.fs || fs,
      align: cell.num ? 'right' : 'left', valign: 'middle', fontFace: cell.num ? FN : F,
      fill: cell.fill ? { color: cell.fill } : undefined, margin: [2, padL, 2, padL] } };
  }));
  s.addTable([head, ...body], { x, y, w: colW.reduce((a, b) => a + b, 0), colW,
    rowH: [hh, ...rows.map(() => rh)], border: { type: 'solid', pt: 0.5, color: C.line },
    fontFace: F, autoPage: false, margin: 0 });
}

// =========================================================================
// P1 封面
// =========================================================================
{
  const s = base(true);
  s.addShape(EL, { x: 9.4, y: -1.9, w: 5.6, h: 5.6, fill: { color: '2656BD', transparency: 58 }, line: noLine });
  chrome(s, '可信取数 · TRUSTED DATA GATEWAY', 'v1.2 / demo-v1.1', '01', true);
  T(s, '数桥 DataBridge', { x: ML, y: 1.45, w: CW, h: 0.9, fontSize: 44, bold: true, color: C.white });
  T(s, '面向 AI Agent 的可信取数平台 —— 让大模型给出的每一个数字，\n都解释得清口径、追得回源头、证得了对错。',
    { x: ML, y: 2.42, w: 11.2, h: 0.85, fontSize: 17, color: 'C7D8F4', lineSpacingMultiple: 1.25 });
  const tags = ['只读 · 零写操作', '8 个冻结指标', '歧义先澄清', '数字可追溯', '三人三模块契约驱动'];
  let cx = ML;
  tags.forEach((tg) => { const w = 0.28 + tg.length * 0.145; chip(s, cx, 3.62, w, tg, { bg: C.white, color: C.white, line: C.white, transparency: 86, lineTransparency: 65, fs: 10.5, h: 0.36 }); cx += w + 0.16; });
  const sw = (CW - 0.24) / 3;
  [['2026-09 全平台净销售额', '17,198,835.91 元'], ['演示主线数据集', '20,000 订单 · 9 个月'], ['自动化测试', '16 入口全绿']]
    .forEach((d, i) => {
      const x = ML + i * (sw + 0.12);
      s.addShape(RR, { x, y: 4.35, w: sw, h: 1.15, rectRadius: 0.08,
        fill: { color: C.white, transparency: 90 }, line: { color: C.white, transparency: 70, pt: 1 } });
      T(s, d[0], { x: x + 0.2, y: 4.52, w: sw - 0.4, h: 0.26, fontSize: 10.5, color: 'A9C0E8' });
      T(s, d[1], { x: x + 0.2, y: 4.82, w: sw - 0.4, h: 0.5, fontSize: d[1].length > 12 ? 15 : 20, bold: true, color: C.white, num: true, margin: 0, fit: 'shrink' });
    });
  T(s, 'A 赛题 · 中国数联 × 华师大 AI 智能体校园黑客松 · 2026-10 ｜ sha256 manifest 锁定',
    { x: ML, y: 6.85, w: CW, h: 0.3, fontSize: 11, color: '9FB6DD' });
  note(s, '各位评委好。我们解决的是企业把数据库交给 AI Agent 后最致命的问题——数字看起来正常，但它是错的。');
}

// =========================================================================
// P2 问题
// =========================================================================
{
  const s = base();
  chrome(s, '01 · 问题', '门槛已经不是“写不写得出 SQL”', '02');
  title(s, 'AI 能拿到数，但企业不敢用这个数');
  const cw = (CW - 0.5) / 3, x0 = ML, y = 1.98, h = 2.62;
  const cards = [
    { ico: '≠', head: '各说各话', num: '221.5 万元', body: '同一个“9月销售额”：净销 1,720 万还是实付 1,941 万？差的正是当月退款，没人说清用哪个口径。' },
    { ico: '⚠', head: '错而不自知', num: '+96.8 万元', body: 'SQL 能跑、不报错，但取消订单混入、退款被一对多累计，9 月净销虚高 5.63%，错误静默通过。' },
    { ico: '✎', head: '自信地编造', num: '8 / 37 题', body: '因果归因、未来预测、写操作、未定义指标——直接 Text-to-SQL 在正式库上全部“自信作答”，无一拒答。' },
  ];
  cards.forEach((c, i) => {
    const x = x0 + i * (cw + 0.25);
    panel(s, x, y, cw, h, { fill: C.upBg, line: C.upLine, shadow: true });
    cardHead(s, x + 0.2, y + 0.2, c.ico, c.head, C.up, cw);
    T(s, c.num, { x: x + 0.2, y: y + 0.72, w: cw - 0.4, h: 0.42, fontSize: 24, bold: true, color: C.up, num: true });
    T(s, c.body, { x: x + 0.2, y: y + 1.25, w: cw - 0.4, h: 1.25, fontSize: 11.5, color: C.ink2, lineSpacingMultiple: 1.18, valign: 'top' });
  });
  panel(s, ML, 4.85, CW, 1.28, { fill: C.panel, line: 'CDDDF7' });
  T(s, [
    { text: 'Text-to-SQL 解决了“能不能拿到数”；企业真正出事的是“这个数字能不能信、敢不敢写进汇报”。', options: { fontSize: 13, color: C.ink2, breakLine: true, paraSpaceAfter: 6 } },
    { text: '37 道业务题实测：直接方案 ', options: { fontSize: 13, color: C.ink2 } },
    { text: '完成 0 题', options: { fontSize: 13, bold: true, color: C.up } },
    { text: '——不是 SQL 写错，而是缺了口径、澄清、安全聚合与边界四层治理。', options: { fontSize: 13, color: C.ink2 } },
  ], { x: ML + 0.28, y: 5.08, w: CW - 0.56, h: 0.85, valign: 'middle', lineSpacingMultiple: 1.2 });
  footer(s, '数字均来自 demo-v1.1 真实计算（正式联调库，非页面模拟数）', '_experiment_formal_out.txt');
  note(s, '企业里出事的不是报错，而是不报错的错数、各说各话的口径、和 AI 越界编造。');
}

// =========================================================================
// P3 同一个问题，两个数字
// =========================================================================
{
  const s = base();
  chrome(s, '02 · 同一个问题', '两个数字 · 差 96.8 万', '03');
  title(s, '问：2026 年 9 月的净销售额是多少？');
  const y = 1.95, h = 2.78, w = 5.72;
  panel(s, ML, y, w, h, { fill: C.upBg, line: C.upLine, shadow: true });
  T(s, '普通 Text-to-SQL（S1）', { x: ML + 0.25, y: y + 0.18, w: w - 0.5, fontSize: 15, bold: true, color: C.up });
  T(s, '18,166,729.12 元', { x: ML + 0.25, y: y + 0.62, w: w - 0.5, fontSize: 31, bold: true, color: C.up, num: true });
  [['偏差', '+967,893.21 元（+5.63%）'], ['SQL', '能执行、无任何报错'], ['37 道业务题完成数', '0']].forEach((r, i) => T(s,
    [{ text: r[0] + '　', options: { color: C.ink3 } }, { text: r[1], options: { bold: true, color: C.up } }],
    { x: ML + 0.25, y: y + 1.42 + i * 0.42, w: w - 0.5, fontSize: 12.5 }));
  T(s, 'VS', { x: 6.42, y: y + 1.15, w: 0.5, h: 0.5, align: 'center', fontSize: 15, bold: true, color: C.ink3 });
  const x2 = 7.0, w2 = 5.71;
  panel(s, x2, y, w2, h, { fill: C.downBg, line: C.downLine, shadow: true });
  T(s, '数桥 S2（完整治理方案）', { x: x2 + 0.25, y: y + 0.18, w: w2 - 0.5, fontSize: 15, bold: true, color: C.down });
  T(s, '17,198,835.91 元', { x: x2 + 0.25, y: y + 0.62, w: w2 - 0.5, fontSize: 31, bold: true, color: C.down, num: true });
  [['偏差', '— 参考真值'], ['SQL', '能执行，且每个数字可追溯'], ['37 道业务题完成数', '37']].forEach((r, i) => T(s,
    [{ text: r[0] + '　', options: { color: C.ink3 } }, { text: r[1], options: { bold: true, color: C.down } }],
    { x: x2 + 0.25, y: y + 1.42 + i * 0.42, w: w2 - 0.5, fontSize: 12.5 }));
  panel(s, ML, 5.05, CW, 1.1, { fill: C.panel, line: 'CDDDF7' });
  T(s, [
    { text: '最危险的是它不报错：', options: { bold: true, color: C.navy } },
    { text: '同一个库、同一个问题，SQL 都跑得通，财务汇报时这就是一场事故。数桥的口径、澄清、安全聚合让数字回到真值。', options: { color: C.ink2 } },
  ], { x: ML + 0.28, y: 5.05, w: CW - 0.56, h: 1.1, valign: 'middle', fontSize: 13, lineSpacingMultiple: 1.2 });
  footer(s, 'S1 为确定性直接 Text-to-SQL 基线；同一正式库、同一问题，差异可逐笔复现', '_对照实验明细_formal.csv · D01');
  note(s, '同一个库同一个问题，S1 报 1,816 万，真值 1,719 万，差了将近 97 万，而且 SQL 不报错。');
}

// =========================================================================
// P4 四道防线
// =========================================================================
{
  const s = base();
  chrome(s, '03 · 产品定位', '业务字典 + 查询计划 + 澄清 + 结果检查', '04');
  title(s, '数字到你手里之前，先过四道关');
  panel(s, ML, 1.98, CW, 1.08, { fill: C.navy, line: C.navy });
  T(s, '数桥 = 业务字典 ＋ 查询计划 ＋ 歧义澄清 ＋ 结果检查',
    { x: ML, y: 1.98, w: CW, h: 1.08, align: 'center', valign: 'middle', fontSize: 20, bold: true, color: C.white });
  const steps = [
    ['1', '统一口径', '8 个指标写进共享契约，页面 / Agent / SQL 服务同一份定义'],
    ['2', '先澄清', '命中歧义词必须问清楚，最多 2 轮，绝不替用户猜'],
    ['3', '安全聚合', '成功状态过滤、退款先按订单预聚合、按退款完成月归属'],
    ['4', '有边界', '因果 / 预测 / 写操作 / 未定义指标——明确拒绝并说明缺什么'],
  ];
  const w = (CW - 0.45) / 4, y = 3.4, h = 2.55;
  steps.forEach((d, i) => {
    const x = ML + i * (w + 0.15);
    panel(s, x, y, w, h, { shadow: true });
    s.addShape(RC, { x: x + 0.18, y, w: w - 0.36, h: 0.05, fill: { color: C.blue } });
    T(s, d[0], { x: x + 0.2, y: y + 0.22, w: 0.5, h: 0.4, fontSize: 13, bold: true, color: C.blue, num: true });
    T(s, d[1], { x: x + 0.2, y: y + 0.62, w: w - 0.4, fontSize: 16, bold: true, color: C.navy });
    T(s, d[2], { x: x + 0.2, y: y + 1.12, w: w - 0.4, h: 1.2, fontSize: 11.5, color: C.ink2, valign: 'top', lineSpacingMultiple: 1.2 });
  });
  footer(s, '接下来分别展开：Agent 怎么理解问题、数字怎么保证正确', 'shared/contracts.py v1.2');
  note(s, '四道防线对应后面成员 2 和成员 1 的展开。');
}

// =========================================================================
// P5 防线一 · 业务字典
// =========================================================================
{
  const s = base();
  chrome(s, '04 · 防线一', '业务字典 · 8 个指标只有一种算法', '05');
  title(s, 'Agent 不临场理解指标，算法写进共享契约');
  const y = 1.98, h = 2.42;
  panel(s, ML, y, 6.0, h, { shadow: true });
  T(s, '5 个基础指标', { x: ML + 0.25, y: y + 0.18, fontSize: 15, bold: true, color: C.navy });
  bullets(s, ['支付订单数（去重 order_id）', '支付人数（去重 customer_id）', '实付金额（仅 success 支付）',
    '成功退款金额（仅 success 退款）', '净销售额 = 实付 − 同期成功退款'], ML + 0.25, y + 0.62, 5.5, 1.7, { fs: 12 });
  const x2 = 6.86;
  panel(s, x2, y, CW - 6.24, h, { fill: C.panel, line: 'CDDDF7', shadow: true });
  T(s, '3 个派生比率（v1.2）', { x: x2 + 0.25, y: y + 0.18, fontSize: 15, bold: true, color: C.navy });
  bullets(s, ['退款率 ＝ 成功退款 / 实付金额', '客单价 ＝ 实付金额 / 支付订单数',
    '支付人均消费 ＝ 实付金额 / 支付人数', '先汇总分子分母再相除；分母为 0 返回 null，比率统一 2 位百分比'],
    x2 + 0.25, y + 0.62, CW - 6.74, 1.7, { fs: 12 });
  panel(s, ML, 4.72, CW, 1.45, { fill: C.downBg, line: C.downLine });
  T(s, [
    { text: '唯一事实来源：', options: { bold: true, color: C.down, fontSize: 13 } },
    { text: '页面、Agent、SQL 服务全部 import 同一份 shared/contracts.py，禁止各自写字面量。\n', options: { color: C.ink2, fontSize: 12.5, breakLine: true } },
    { text: '退款率分母必须是实付金额而非净销售额——否则“退款越多、退款率越被放大”。', options: { color: C.ink2, fontSize: 12.5 } },
  ], { x: ML + 0.28, y: 4.9, w: CW - 0.56, h: 1.1, valign: 'middle', lineSpacingMultiple: 1.3 });
  footer(s, '派生比率在 Agent 网关层由两次分量查询组合，执行层零改动（RISK-04 已缓解）', 'config/metrics.json · shared/contracts.py');
  note(s, '比如退款率，字典写死分母是实付金额，不是净销售额。');
}

// =========================================================================
// P6 防线二 · 澄清
// =========================================================================
{
  const s = base();
  chrome(s, '05 · 防线二', '口径不明确，先问，不猜', '06');
  title(s, '把口径选择权交还给用户');
  const y = 1.98;
  panel(s, ML, y, 7.35, 4.15, { shadow: true });
  const bubble = (yy, who, text, mine) => {
    const x = mine ? 3.55 : ML + 0.28, w = 3.5, fill = mine ? C.white : C.blueSoft, line = mine ? C.line : 'CBD9F7';
    panel(s, x, yy, w, 0.62, { fill, line });
    T(s, who, { x: x + 0.14, y: yy + 0.07, fontSize: 9.5, color: C.ink3 });
    T(s, text, { x: x + 0.14, y: yy + 0.26, w: w - 0.28, fontSize: 11.5, color: C.ink });
  };
  bubble(y + 0.22, '用户', '9月的销售额是多少', true);
  panel(s, ML + 0.28, y + 1.02, 3.5, 1.42, { fill: C.blueSoft, line: 'CBD9F7' });
  T(s, '数桥：你说的「销售额」是指？', { x: ML + 0.42, y: y + 1.12, fontSize: 11.5, color: C.navy, bold: true });
  T(s, '○ 净销售额 — 实付 − 同期成功退款\n○ 实付金额 — 不做退款扣减',
    { x: ML + 0.42, y: y + 1.44, fontSize: 10.5, color: C.ink2, lineSpacingMultiple: 1.25 });
  bubble(y + 2.62, '用户（选择）', '净销售额', true);
  panel(s, ML + 0.28, y + 3.4, 3.5, 0.6, { fill: C.downBg, line: C.downLine });
  T(s, '17,198,835.91 元 ＋ 口径/SQL/版本', { x: ML + 0.42, y: 3.4 + y, w: 3.2, h: 0.6, valign: 'middle', fontSize: 10.5, bold: true, color: C.down });
  const x2 = 8.25, w2 = CW - (8.25 - ML);
  panel(s, x2, y, w2, 1.95, { fill: C.upBg, line: C.upLine });
  T(s, '两个候选当月相差', { x: x2 + 0.25, y: y + 0.2, fontSize: 12.5, color: C.ink2 });
  T(s, '2,215,508.08 元', { x: x2 + 0.25, y: y + 0.55, fontSize: 26, bold: true, color: C.up, num: true });
  T(s, '净销 17,198,835.91 与实付 19,414,343.99 的差', { x: x2 + 0.25, y: y + 1.32, fontSize: 10.5, color: C.ink3 });
  panel(s, x2, y + 2.2, w2, 1.95, { fill: C.panel, line: 'CDDDF7' });
  bullets(s, ['命中歧义词表必须先澄清，禁止默认猜测', '单次提问最多 2 轮，超过即降级“数据不足”',
    '评价标准模糊（“哪个地区最好”）同样必须追问'], x2 + 0.25, y + 2.45, w2 - 0.5, 1.5, { fs: 11.5, after: 8 });
  footer(s, '正确澄清：开发集 8 题 / 保留集 8 题，模型与规则模式行为一致', 'member2_workflow_test.py');
  note(s, '“销售额”在业务里是歧义词。数桥把选择权交还用户，同一批人不会再吵出两个数字。');
}

// =========================================================================
// P7 防线三 · 安全聚合
// =========================================================================
{
  const s = base();
  chrome(s, '06 · 防线三', '安全聚合 · 近 97 万的错怎么产生', '07');
  title(s, '三个独立致错来源（正式库 37 题归因）');
  const items = [
    ['18 题', '未排除失败 / 取消订单', '直接 SQL 不过滤状态，failed / pending / cancelled 订单与退款混入统计'],
    ['16 题', 'JOIN 一对多扇出', 'orders ⨝ refunds 明细直连，一单多退时实付金额被按退款条数重复累计'],
    ['13 题', '退款按支付月归属', '退款被挂回订单支付月，后续退款持续回溯改写已结账的历史月份'],
  ];
  const w = (CW - 0.5) / 3, y = 1.98, h = 2.5;
  items.forEach((d, i) => {
    const x = ML + i * (w + 0.25);
    panel(s, x, y, w, h, { shadow: true });
    T(s, d[0], { x: x + 0.22, y: y + 0.2, w: w - 0.44, fontSize: 26, bold: true, color: C.up, num: true });
    T(s, d[1], { x: x + 0.22, y: y + 0.85, w: w - 0.44, fontSize: 14, bold: true, color: C.navy });
    T(s, d[2], { x: x + 0.22, y: y + 1.32, w: w - 0.44, h: 1.05, fontSize: 11, color: C.ink2, valign: 'top', lineSpacingMultiple: 1.2 });
  });
  panel(s, ML, 4.78, CW, 1.4, { fill: C.navy, line: C.navy });
  T(s, [
    { text: '数桥两侧独立聚合（华东 2026-09）　', options: { bold: true, color: C.white, fontSize: 13 } },
    { text: '实付 7,786,231.39 − 退款 955,887.84 = 净销 6,830,343.55 元', options: { color: '9DC3F5', fontSize: 15, bold: true } },
  ], { x: ML + 0.3, y: 4.95, w: CW - 0.6, h: 0.5, valign: 'middle' });
  T(s, '退款先按 order_id 预聚合、再取订单快照地区，结构上不可能重复累计：同一订单追加 5 笔各 1000 元退款，净销精确下降 5000，实付不动。',
    { x: ML + 0.3, y: 5.5, w: CW - 0.6, h: 0.5, fontSize: 11.5, color: 'BCCDF0', valign: 'middle' });
  footer(s, '归因方法：从正确管线出发每次只引入一个缺陷，独立量化致错题数（可多因叠加）', 'run_experiment.py --source formal');
  note(s, '结构上保证退款不被重复累计，同一订单多退多少，净销就精确降多少。');
}

// =========================================================================
// P8 IS-001
// =========================================================================
{
  const s = base();
  chrome(s, '07 · 口径决策 IS-001', '44% 的退款是跨月的', '08');
  title(s, '历史账不能被后续退款改写');
  const w = (CW - 0.5) / 3, y = 1.98, h = 1.72;
  const stats = [
    ['1,356 / 3,062 笔', '跨月退款占比 44.28%'],
    ['45.55%', '跨月退款金额占比（6,176,762.17 元）'],
    ['−329,335.21 元', '2026-09 华东按支付月归属被回溯改写（−4.82%）'],
  ];
  stats.forEach((d, i) => {
    const x = ML + i * (w + 0.25);
    panel(s, x, y, w, h, { fill: C.panel, line: 'CDDDF7', shadow: true });
    T(s, d[0], { x: x + 0.22, y: y + 0.28, w: w - 0.44, fontSize: 22, bold: true, color: i === 2 ? C.up : C.navy, num: true, fit: 'shrink' });
    T(s, d[1], { x: x + 0.22, y: y + 0.98, w: w - 0.44, fontSize: 11.5, color: C.ink2, valign: 'top' });
  });
  panel(s, ML, 4.02, CW, 2.12, { fill: C.downBg, line: C.downLine });
  T(s, '三人决策（2026-10-06 签字冻结）：退款按「退款完成月」归属 —— 方案 A',
    { x: ML + 0.28, y: 4.2, fontSize: 14.5, bold: true, color: C.down });
  bullets(s, [
    '方案 A（refund_time）：净销衡量期间实际沉淀收入，跨月退款不追溯改写已结账月份，现行 S2 / 执行层一致',
    '方案 B（pay_time）：9 月退款会回头改 8 月报表，已发布月度结论持续漂移，违背“口径冻结、结果可追溯”',
    '守恒校验：两口径全期总额相等，差异矩阵逐格等于逐笔退款独立重算',
  ], ML + 0.28, 4.62, CW - 0.56, 1.4, { fs: 11.5, after: 6 });
  footer(s, '正式库 demo-v1.1 自然跨月退款真实测量（非人工注入）', '口径冻结确认单_2026-10-04.md · is001_refund_timing.py');
  note(s, '接近一半退款发生在支付之后的月份，方案 A 让历史月份零漂移，已三人冻结。');
}

// =========================================================================
// P9 防线四 · 拒答
// =========================================================================
{
  const s = base();
  chrome(s, '08 · 防线四', '不支持就说不支持，绝不编', '09');
  title(s, '四类越界请求，各有明确原因码');
  makeTable(s,
    ['问题', '数桥回答', '原因码'],
    [
      { 0: '为什么华南 9 月净销售额下降', 1: '数据不足：缺营销 / 竞品 / 价格等外部变量', 2: { t: 'causal_reasoning_unsupported', num: true, fs: 10 } },
      { 0: '预测下个月净销售额', 1: '只查历史数据，不提供预测能力', 2: { t: 'no_forecast_capability', num: true, fs: 10 } },
      { 0: '把订单表里 9 月的记录删掉', 1: '只读平台，拒绝一切写操作（安全红线）', 2: { t: 'write_operation_refused', num: true, fs: 10 } },
      { 0: '复购率 / 转化率是多少', 1: '二期指标，当前版本明确拒答', 2: { t: 'derived_metric_unsupported', num: true, fs: 10 } },
    ].map((o) => [o[0], o[1], o[2]]),
    ML, 2.05, [3.7, 5.39, 3.0], { fs: 12, hh: 0.45, rh: 0.72 });
  panel(s, ML, 5.55, CW, 0.78, { fill: C.panel, line: 'CDDDF7' });
  T(s, '拒答不是能力缺失，是可信承诺：每条拒答都给出原因码、缺少的信息与“下一步可以怎么问”；全题库无依据编造为 0。',
    { x: ML + 0.28, y: 5.55, w: CW - 0.56, h: 0.78, valign: 'middle', fontSize: 12.5, color: C.ink2 });
  footer(s, '写操作、预测、因果、未定义比率在调用模型前即被本地护栏拦截（13 题零 token，见 P14）', 'shared/contracts.py · ReasonCode');
  note(s, '每条拒答都说明缺什么、下一步怎么问，绝不编造。');
}

// =========================================================================
// P10 现场演示
// =========================================================================
{
  const s = base(true);
  chrome(s, '09 · 现场演示 · LIVE', 'Streamlit → /agent/query → SQLite', '10', true);
  T(s, '2026 年 9 月，华南怎么了？', { x: ML, y: 1.42, w: CW, h: 0.7, fontSize: 32, bold: true, color: C.white });
  const steps = [
    ['1', '数据接入', '20,000 单 · 质检 0/0'], ['2', '分地区环比', '华南 −15.72%'],
    ['3', '口径澄清', '与②同数收敛'], ['4', 'Agent 简报', '点名华南 · 不归因'],
    ['5', '结果依据', '真实 SQL + query_id'],
  ];
  const n = 5, gap = 0.30, w = (CW - gap * (n - 1)) / n, y = 2.55, h = 1.72;
  steps.forEach((d, i) => {
    const x = ML + i * (w + gap);
    s.addShape(RR, { x, y, w, h, rectRadius: 0.09, fill: { color: C.white, transparency: 90 }, line: { color: C.white, transparency: 72, pt: 1 } });
    T(s, d[0], { x: x + w / 2 - 0.21, y: y + 0.18, w: 0.42, h: 0.42, align: 'center', valign: 'middle', fontSize: 14, bold: true, color: C.navy, fill: { color: C.white }, margin: 0, num: true });
    T(s, d[1], { x: x + 0.1, y: y + 0.72, w: w - 0.2, align: 'center', fontSize: 13.5, bold: true, color: C.white });
    T(s, d[2], { x: x + 0.1, y: y + 1.12, w: w - 0.2, align: 'center', fontSize: 10.5, color: 'B9CDF0' });
    if (i < n - 1) T(s, '→', { x: x + w + 0.02, y: y + 0.55, w: gap, h: 0.5, align: 'center', valign: 'middle', fontSize: 15, color: '8FA8D2' });
  });
  const tags = [
    ['净销 17,198,835.91 元（环比 −6.47%）', C.blueSoft, C.white, 'FFFFFF'],
    ['华南 ▼15.72% · 减 765,507.42 元', 'C62828', C.white, 'FFB4B4'],
    ['华中 ▲1.53% · 唯一正增长', '1C7A44', C.white, 'A0E1B9'],
  ];
  let cx = ML;
  tags.forEach(([t, bg, col, ln]) => { const ww = 0.5 + t.length * 0.135; chip(s, cx, 4.72, ww, t, { bg, color: col, line: ln, transparency: 30, lineTransparency: 25, fs: 11, h: 0.42 }); cx += ww + 0.2; });
  T(s, 'HTTP 黄金路径自动化实测 14/14 通过，连跑 3 次数字逐字一致。live 默认走真实 DeepSeek（理解约 0.9s），断网一键切离线 rules，数字 67/67 一致、演示不翻车。',
    { x: ML, y: 6.52, w: CW, h: 0.34, fontSize: 10.5, color: '9FB6DD' });
  note(s, '五步操作：质检、问环比、澄清验证同数、Agent 简报、翻真实 SQL。全程真实 live 链路。');
}

// =========================================================================
// P11 证据链
// =========================================================================
{
  const s = base();
  chrome(s, '10 · 结果可追溯', '每个数字都能翻底账', '11');
  title(s, '返回数字，也返回它的整个生产过程');
  panel(s, ML, 1.98, CW, 2.5, { fill: C.dark, line: C.dark });
  const mono = ['用户提问  →  共享契约(指标 / 枚举)',
    '→  结构化查询计划(JSON，白名单过滤)',
    '→  只读 SQL（参数化、整数分、半开区间、禁写操作）',
    '→  结果 ＋ 警告 ＋ query_id',
    'GET /v1/query-records/{id}  随时复查当时的 SQL 与参数'];
  mono.forEach((l, i) => T(s, l, { x: ML + 0.35, y: 2.2 + i * 0.44, w: CW - 0.7, fontFace: MONO, fontSize: 13,
    color: i === 4 ? '7FD3A1' : 'C6D5F3' }));
  const w = (CW - 0.3) / 2;
  panel(s, ML, 4.78, w, 1.42, { shadow: true });
  T(s, '注入与写操作防护', { x: ML + 0.25, y: 4.96, fontSize: 13.5, bold: true, color: C.navy });
  T(s, "SQL 注入用例（' OR 1=1 --）返回 422；DELETE / UPDATE 等写词在 Agent 层直接拒答。",
    { x: ML + 0.25, y: 5.35, w: w - 0.5, fontSize: 11.5, color: C.ink2, lineSpacingMultiple: 1.2 });
  panel(s, ML + w + 0.3, 4.78, w, 1.42, { shadow: true });
  T(s, '只读连接 · 哈希不变', { x: ML + w + 0.55, y: 4.96, fontSize: 13.5, bold: true, color: C.navy });
  T(s, '数据库以只读方式连接，测试后文件哈希不变（test_10 只读不变量）。',
    { x: ML + w + 0.55, y: 5.35, w: w - 0.5, fontSize: 11.5, color: C.ink2, lineSpacingMultiple: 1.2 });
  footer(s, '口径、来源表、数据集版本、生成 SQL 与参数随结果同屏返回', '/v1/query-records/{query_id}');
  note(s, '数字之外还返回口径、查了哪些表、执行了什么 SQL、数据集版本。');
}

// =========================================================================
// P12 数据质检
// =========================================================================
{
  const s = base();
  chrome(s, '11 · 数据准入', '数据先过质检，才允许被查询', '12');
  title(s, '脏数据在入库环节就被挡住');
  const y = 1.98, h = 4.28, w = (CW - 0.3) / 2;
  panel(s, ML, y, w, h, { fill: C.downBg, line: C.downLine, shadow: true });
  T(s, '干净库 demo-v1.1', { x: ML + 0.25, y: y + 0.2, fontSize: 15, bold: true, color: C.down });
  bullets(s, ['0 严重问题 / 0 警告，70 项 manifest 一致性校验全过',
    '20,000 订单 / 3,492 退款 / 2,000 客户，覆盖 2026-01~09',
    '五地区词表统一，内容 sha256 锁定（DS-001）',
    '超额退款 0 例：同一订单累计退款不得超过实付'],
    ML + 0.25, y + 0.62, w - 0.5, 2.0, { fs: 12, after: 9 });
  panel(s, ML + 0.25, y + 2.95, w - 0.5, 1.1, { fill: C.white, line: C.downLine });
  T(s, '红线：严重问题未解决前，任何查询结果不得作为结论。',
    { x: ML + 0.45, y: 2.95 + y, w: w - 0.9, h: 1.1, valign: 'middle', fontSize: 11.5, bold: true, color: C.down });
  const x2 = ML + w + 0.3;
  panel(s, x2, y, w, h, { shadow: true });
  T(s, '九类异常固件 + 导入器', { x: x2 + 0.25, y: y + 0.2, fontSize: 15, bold: true, color: C.navy });
  bullets(s, ['重复主键、负金额、坏时间戳、缺列、必填缺失', '外键悬空、金额类型错误、异常金额、超额退款',
    '导入器审计：拦截 6 错 5 警，质检不过即拒绝建库', '同一订单累计退款 > 实付 → 直接拒绝入库'],
    x2 + 0.25, y + 0.62, w - 0.5, 2.0, { fs: 12, after: 9 });
  panel(s, x2 + 0.25, y + 2.95, w - 0.5, 1.1, { fill: C.warnBg, line: 'EFD9AC' });
  T(s, '真实教训（BUG-01）：8.5 万条演示数据曾查出 3,132 单超额退款、净销多扣约 45.9 万；无放回抽单 + 水位线封顶重生成后归零。',
    { x: x2 + 0.45, y: 2.95 + y, w: w - 0.9, h: 1.1, valign: 'middle', fontSize: 10.5, color: '6B4E12', lineSpacingMultiple: 1.18 });
  footer(s, '导入器与 70 项校验见成员 1 交付；F01/F02 八异常场景 scenario_test 17 项通过', 'scripts/import_dataset.py · validate_demo.py');
  note(s, '我们自己的演示数据也曾查出超额退款，修复机制让正式库归零。');
}

// =========================================================================
// P13 S1 vs S2 实验
// =========================================================================
{
  const s = base();
  chrome(s, '成员 1 · 实验结果', '37 开发题 + 30 保留题', '13');
  title(s, '0 / 37 对 37 / 37：治理层增量被逐题量化');
  makeTable(s,
    ['指标（开发集 37 题）', 'S1 直接', 'S2 数桥'],
    [
      ['任务完成率', { t: '0 / 37（0%）', num: true, color: C.up, bold: true }, { t: '37 / 37（100%）', num: true, color: C.down, bold: true }],
      ['数值错误（元数据对、数字错）', { t: '21', num: true }, { t: '0', num: true, bold: true, color: C.down }],
      ['无依据编造', { t: '8', num: true }, { t: '0', num: true, bold: true, color: C.down }],
      ['正确澄清', { t: '0', num: true }, { t: '8', num: true, bold: true, color: C.down }],
    ], ML, 1.98, [3.35, 1.52, 1.52], { fs: 10.5, hh: 0.38, rh: 0.5 });
  T(s, '保留集 30 题盲测（开发期不调参）同样 30/30。',
    { x: ML, y: 4.45, w: 6.4, fontSize: 10.5, color: C.ink2 });
  panel(s, ML, 4.82, 6.39, 1.32, { fill: C.panel, line: 'CDDDF7' });
  T(s, [
    { text: 'S1 是确定性行为基线（无真实 LLM），用于隔离治理层价值。\n', options: { fontSize: 11, color: C.ink2, breakLine: true } },
    { text: '换上真实大模型还守不守得住？下一页用同一批 67 题给实测答案。', options: { fontSize: 11, bold: true, color: C.navy } },
  ], { x: ML + 0.22, y: 4.95, w: 5.95, h: 1.1, valign: 'middle', lineSpacingMultiple: 1.2 });
  const x2 = 7.25, w2 = CW - (7.25 - ML), cy = 1.98, ch = 1.08, g = 0.1;
  const side = [
    ['跨团队同数锚点 F07', 'formal_dataset_test 35 项，9 月五指标×全平台/五地区共 25 项地区核对，差值 0 分。', C.panel, C.navy],
    ['测试金字塔', '16 个自动化入口全绿：真实模型 67 题复测、smoke 26、开发 37、保留 30、F01–F08、live 15、formal 35 等。', C.panel, C.navy],
    ['诚实声明 → 真实模型复测', '不写未验证数字；真实 DeepSeek 复测见下一页 P14。', C.downBg, C.down],
    ['一键复现', 'run_testset.py 开发集/保留集 · run_experiment.py --source formal · formal_dataset_test.py', C.white, C.navy],
  ];
  side.forEach((d, i) => {
    const y = cy + i * (ch + g);
    panel(s, x2, y, w2, ch, { fill: d[2], line: d[2] === C.downBg ? C.downLine : (d[2] === C.white ? C.line : 'CDDDF7') });
    T(s, d[0], { x: x2 + 0.2, y: y + 0.12, w: w2 - 0.4, fontSize: 12.5, bold: true, color: d[3] });
    T(s, d[1], { x: x2 + 0.2, y: y + 0.42, w: w2 - 0.4, h: ch - 0.5, fontSize: i === 3 ? 9.5 : 10.5,
      color: C.ink2, valign: 'top', lineSpacingMultiple: 1.12, fontFace: i === 3 ? MONO : F });
  });
  footer(s, 'S1 失败的 37 题恰好分布在三道防线：数值 21 / 澄清 8 / 编造与写操作 8', 'run_experiment.py --source formal');
  note(s, '37 道题逐题真实计算，错在哪一层、错多少钱都可复现。换成真实大模型看下一页。');
}

// =========================================================================
// P14 真实大模型复测（新增核心页）
// =========================================================================
{
  const s = base();
  chrome(s, '成员 2 · 真实模型', 'DeepSeek 全量复测 · 2026-10-06', '14');
  title(s, [{ text: '换上真实 DeepSeek，67 个数字', options: { color: C.navy } },
    { text: '一个没变', options: { color: C.down } }]);
  const lw = 5.78, rx = ML + lw + 0.32, rw = CW - lw - 0.32, y = 1.95;
  panel(s, ML, y, lw, 2.42, { fill: C.dark, line: C.dark });
  const lines = [
    ['用户自然语言问题', 'C6D5F3'],
    ['真实 DeepSeek：问题 → 结构化槽位', '8FB4FF'],
    ['◀ 模型到此为止 · 不碰数据库', 'F0B860'],
    ['本地治理：字典 · 澄清 · 护栏 · 只读 SQL · 聚合', 'C6D5F3'],
    ['可信结果 ＋ SQL ＋ query_id', '7FD3A1'],
  ];
  lines.forEach((l, i) => T(s, l[0], { x: ML + 0.28, y: y + 0.2 + i * 0.43, w: lw - 0.56,
    fontFace: MONO, fontSize: 11.5, color: l[1] }));
  panel(s, ML, y + 2.6, lw, 1.92, { fill: C.downBg, line: C.downLine, shadow: true });
  s.addShape(RR, { x: ML + 0.24, y: y + 2.76, w: 0.32, h: 0.32, rectRadius: 0.06, fill: { color: C.down } });
  T(s, '0', { x: ML + 0.24, y: y + 2.76, w: 0.32, h: 0.32, align: 'center', valign: 'middle', fontSize: 13, bold: true, color: C.white, num: true });
  T(s, '13 题在模型调用前就被拦下', { x: ML + 0.66, y: y + 2.77, w: lw - 0.9, h: 0.32, fontSize: 14, bold: true, color: C.down });
  T(s, '因果 / 预测 / 写操作 / 口径冲突类问题由本地护栏前置拦截——问题不外发、零 token，既不泄密又省钱。规则 / 模型一键切换，数字 67/67 一致。',
    { x: ML + 0.24, y: y + 3.22, w: lw - 0.48, fontSize: 11, color: C.ink2, valign: 'top', lineSpacingMultiple: 1.22 });
  makeTable(s,
    ['正式库 demo-v1.1 实测', '结果'],
    [
      ['开发集 37 题', { t: '37 / 37 正确', num: true, color: C.down, bold: true }],
      ['保留集 30 题（盲测 · 未调参）', { t: '30 / 30 正确', num: true, color: C.down, bold: true }],
      ['与离线规则信封（含全部数据行）', { t: '67 / 67 逐字段一致', num: true, color: C.down, bold: true }],
      ['无依据编造', { t: '0', num: true, bold: true }],
      ['终态执行失败（1 题重试后成功）', { t: '0', num: true, bold: true }],
    ], rx, y, [4.16, rw - 4.16], { fs: 10.5, hh: 0.36, rh: 0.405 });
  const sw = (rw - 0.24) / 3, sy = y + 2.36;
  stat(s, rx, sy, sw, 1.02, '真实调用模型', '54 题', { fs: 17 });
  stat(s, rx + sw + 0.12, sy, sw, 1.02, '护栏前零调用', '13 题', { fs: 17, vColor: C.down });
  stat(s, rx + 2 * (sw + 0.12), sy, sw, 1.02, '67 题实付成本', '¥0.023', { fs: 17 });
  panel(s, rx, sy + 1.18, rw, 0.98, { fill: C.panel, line: 'CDDDF7' });
  T(s, '平均 0.93s/题（p90 1.03s，最大 3.67s 即重试题）；缓存命中 62,208 token。请求名 deepseek-chat 经官方别名实际服务 deepseek-flash（V4.1-Flash）。',
    { x: rx + 0.2, y: sy + 1.18, w: rw - 0.4, h: 0.98, valign: 'middle', fontSize: 10.5, color: C.ink2, lineSpacingMultiple: 1.2 });
  footer(s, '模型只做语言理解；口径、聚合、拒答与计算全部本地，模型可替换而信任不打折', '_LLM真实模型复测明细.csv · 测试报告 §4.2');
  note(s, '模型全程碰不到数据库。换真实 DeepSeek 重跑 67 题数字一个不差，13 题零调用，总共不到三分钱。');
}

// =========================================================================
// P15 系统架构
// =========================================================================
{
  const s = base();
  chrome(s, '14 · 系统架构', '三人三模块 · 契约驱动', '15');
  title(s, '独立开发，靠一份冻结契约严丝合缝');
  panel(s, ML, 1.95, CW, 3.28, { fill: C.dark, line: C.dark });
  const arch = [
    ['Streamlit 产品页面（成员 3）', '8FB4FF'],
    ['  ├─ mock 参考实现            // 现场保底，开箱零依赖', '7D93BD'],
    ['  └─ live ─▶ POST /agent/query', 'C6D5F3'],
    ['        AI 工作流（成员 2）   // 规则 / 真实 DeepSeek 一键切换 · 两轮澄清', '8FB4FF'],
    ['          · 槽位白名单校验     // 模型只提建议，执行在本地', '7FD3A1'],
    ['          · 比率=两次分量查询组合 // 分子分母溯源 + 数据集指纹校验', '7FD3A1'],
    ['        ▼ POST /v1/query', 'C6D5F3'],
    ['FastAPI 查询服务（成员 1）：计划校验 / 版本协商 / 只读 SQLite（整数分）', '8FB4FF'],
  ];
  arch.forEach((l, i) => T(s, l[0], { x: ML + 0.32, y: 2.16 + i * 0.37, w: CW - 0.64,
    fontFace: MONO, fontSize: 11, color: l[1] }));
  const w = (CW - 0.3) / 3, y = 5.42, h = 1.28;
  [['契约 v1.2', '指标 / 状态 / 维度 / 地区枚举全部冻结，CHANGELOG 可追溯'],
   ['数据集版本', '内容 sha256 哈希；DS-001 五地区统一；DS-004 正式库主线'],
   ['联调方式', 'mock_server 先行，契约测试与 35 项同数锚点收口，互不等待']]
    .forEach((d, i) => {
      const x = ML + i * (w + 0.15);
      panel(s, x, y, w, h, { fill: C.panel, line: 'CDDDF7' });
      T(s, d[0], { x: x + 0.2, y: y + 0.14, fontSize: 12.5, bold: true, color: C.navy });
      T(s, d[1], { x: x + 0.2, y: y + 0.46, w: w - 0.4, fontSize: 10.5, color: C.ink2, valign: 'top', lineSpacingMultiple: 1.15 });
    });
  footer(s, '页面 · Agent · SQL 服务对同一问题给出相同数字（F07 逐分一致）', 'databridge/ · agent/ · app/');
  note(s, '三个人按同一份契约独立交付，再用自动化测试证明拼得起来。');
}

// =========================================================================
// P16 当前限制
// =========================================================================
{
  const s = base();
  chrome(s, '15 · 当前限制', '如实说明 · 分工文档 §10', '16');
  title(s, '边界讲清楚，数字才可信');
  const y = 1.98, h = 4.3, w = (CW - 0.3) / 2;
  panel(s, ML, y, w, h, { shadow: true });
  T(s, '已知限制（6）', { x: ML + 0.25, y: y + 0.2, fontSize: 15, bold: true, color: C.navy });
  bullets(s, [
    '固定种子模拟业务数据（2 万单 / 2026-01~09），不代表真实经营',
    '真实模型仅验证单一供应商（deepseek-flash）与 67 道零售题；跨模型 / 跨行业题集 / 长周期稳定性未测',
    '模型只做“问题→槽位”；LLM 直接生成 SQL 不在产品架构内，S1 保留为确定性对照',
    '比率在 Agent 层组合，/v1/query 仍只接受 5 个基础指标',
    '2 维度、5+3 指标；同比、预测、因果、复购率明确不做',
    '未做换机全新部署验证；上传 / 激活闭环不在本次演示范围',
  ], ML + 0.25, y + 0.62, w - 0.5, 3.5, { fs: 11.5, after: 10 });
  const x2 = ML + w + 0.3;
  panel(s, x2, y, w, h, { fill: C.downBg, line: C.downLine, shadow: true });
  T(s, '下一步路线', { x: x2 + 0.25, y: y + 0.2, fontSize: 15, bold: true, color: C.down });
  bullets(s, [
    '已达成：真实 DeepSeek 67 题复测——37/37、30/30、0 编造，成本 ¥0.023',
    '近期：更多模型供应商与跨行业题集验证；datasets/inspect 上传激活闭环',
    '二期：复购率等更多派生指标、更多分析维度',
    '工程化：换机部署脚本（F08）、并发 / 负载测试',
  ], x2 + 0.25, y + 0.62, w - 0.5, 3.5, { fs: 12, after: 14 });
  footer(s, '成本 0.023 元、时延 0.93s 均为实测；不使用任何未经验证的效果数据', 'docs/测试报告.md §4.2 / §6');
  note(s, '主动讲限制是加分项：做到了什么、只验证了哪家模型、什么没测，全部摊开讲。');
}

// =========================================================================
// P17 结尾
// =========================================================================
{
  const s = base(true);
  s.addShape(EL, { x: 9.6, y: 3.4, w: 5.4, h: 5.4, fill: { color: '2656BD', transparency: 72 }, line: noLine });
  chrome(s, '16 · 结语 & Q&A', '谢谢评委', '17', true);
  T(s, 'AI 取数的门槛，不是写不写得出 SQL，\n而是数字能不能被信任。',
    { x: ML, y: 1.62, w: 11.4, h: 1.5, fontSize: 30, bold: true, color: C.white, lineSpacingMultiple: 1.25 });
  T(s, '数桥做的，就是 Agent 与企业数据之间的这层信任。',
    { x: ML, y: 3.28, w: CW, fontSize: 16, color: 'D7E3FB' });
  const qa = ['解决什么问题', '与 Text-to-SQL 区别', '为何选零售场景', '数据从哪来', '如何证明正确', '真实大模型效果如何', '限制与下一步'];
  let cx = ML, cy = 4.18, lineW = 0;
  qa.forEach((q) => {
    const ww = 0.34 + q.length * 0.15;
    if (lineW + ww > CW) { lineW = 0; cy += 0.52; }
    chip(s, cx + lineW, cy, ww, q, { bg: C.white, color: C.white, line: C.white, transparency: 86, lineTransparency: 65, fs: 10.5, h: 0.38 });
    lineW += ww + 0.18;
  });
  T(s, '答疑分工：产品与演示 → 成员 3　·　Agent 机制 → 成员 2　·　指标口径 / 质检 / 实验 → 成员 1',
    { x: ML, y: 5.72, w: CW, fontSize: 12, color: 'A9C0E8' });
  T(s, '数桥 DataBridge · 中国数联 × 华师大 AI 智能体校园黑客松 · demo-v1.1 · 2026-10',
    { x: ML, y: 6.85, w: CW, fontSize: 11, color: '93ACD6' });
  note(s, '金句收尾后进入提问；每个公共问题都有对应章节和实测数字支撑。');
}

const out = path.join(ROOT, 'docs', '答辩幻灯片.pptx');
pres.writeFile({ fileName: out }).then((f) => console.log('PPTX 已生成：', f));
