// Markdown → Word converter for TalentHub docs.
// Reads every TalentHub_*.md in /docs/src and writes a same-named .docx into /docs, using `marked` + `docx`.
// Run from repo root: `node scripts/convert-docs.mjs`
//
// 2026-09-01 樣式改版：專業排版——深藍表頭＋隔行網底表格、標題階層配色、
// 程式碼區塊盒、引言側邊條、每個「# 部」從新頁開始、頁尾頁碼。
// 樣式常數集中在下方 THEME，要換配色改那裡即可。

import { marked } from 'marked';
import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  HeadingLevel,
  PageNumber,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} from 'docx';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..');
// Markdown 來源放在 docs/src，產生的 .docx 放在 docs/。
// 這樣 docs/ 底下只留給人看的 Word 檔，來源檔不會混在一起。
const DOCS_DIR = path.join(REPO_ROOT, 'docs');
const SRC_DIR = path.join(DOCS_DIR, 'src');

const MONO_FONT = 'Consolas';
const ZH_FONT = 'Microsoft JhengHei';

// ── 配色主題（十六進位、不含 #）──────────────────────────────
const THEME = {
  accent: '1F4E79',      // 標題與表頭：深藍
  accentSoft: '2E6DA4',  // 次級標題
  text: '333333',
  muted: '595959',
  tableBorder: 'C9D6E4', // 表格細框線
  tableBand: 'F2F6FA',   // 表格隔行網底
  codeBg: 'F7F8FA',      // 程式碼區塊底色
  codeBorder: 'E1E4E8',
  codeInkBg: 'EFF1F4',   // 行內 code 底色
  quoteBg: 'F7FAFC',     // 引言底色
  rule: 'D0D7DE',        // 分隔線
};

const HEADING_MAP = {
  1: HeadingLevel.HEADING_1,
  2: HeadingLevel.HEADING_2,
  3: HeadingLevel.HEADING_3,
  4: HeadingLevel.HEADING_4,
  5: HeadingLevel.HEADING_5,
  6: HeadingLevel.HEADING_6,
};

// 把含 \n 的文字拆成多個 run，中間補換行（保住引言區塊裡逐行的版本資訊）。
function pushTextWithBreaks(runs, text, opts) {
  const parts = String(text).split('\n');
  parts.forEach((part, i) => {
    if (i > 0) runs.push(new TextRun({ break: 1 }));
    if (part) runs.push(new TextRun({ text: part, ...opts }));
  });
}

function inlineToRuns(tokens, opts = {}) {
  const runs = [];
  for (const t of tokens || []) {
    switch (t.type) {
      case 'text':
        if (t.tokens) {
          runs.push(...inlineToRuns(t.tokens, opts));
        } else {
          pushTextWithBreaks(runs, t.text, opts);
        }
        break;
      case 'strong':
        runs.push(...inlineToRuns(t.tokens, { ...opts, bold: true }));
        break;
      case 'em':
        runs.push(...inlineToRuns(t.tokens, { ...opts, italics: true }));
        break;
      case 'codespan': {
        // 深色表頭（opts 帶 color）時不上底色，避免灰底疊在深藍上。
        const style = opts.color
          ? { font: MONO_FONT, ...opts }
          : { font: MONO_FONT, shading: { fill: THEME.codeInkBg }, color: '24292F', ...opts };
        runs.push(new TextRun({ text: t.text, ...style }));
        break;
      }
      case 'link':
        runs.push(...inlineToRuns(t.tokens, { ...opts, color: '0563C1', underline: {} }));
        break;
      case 'br':
        runs.push(new TextRun({ break: 1 }));
        break;
      case 'del':
        runs.push(...inlineToRuns(t.tokens, { ...opts, strike: true }));
        break;
      case 'html':
        // Skip HTML tags; emit raw text only if it has visible content.
        if (t.text && !/^<[^>]+>$/.test(t.text.trim())) {
          pushTextWithBreaks(runs, t.text, opts);
        }
        break;
      default:
        if (t.text) pushTextWithBreaks(runs, t.text, opts);
    }
  }
  return runs;
}

function listItemRuns(item, opts = {}) {
  // Try to find inline tokens; marked nests differently for tight vs loose lists.
  if (item.tokens && item.tokens[0]) {
    const first = item.tokens[0];
    if (first.tokens) return inlineToRuns(first.tokens, opts);
    if (first.type === 'text') return [new TextRun({ text: first.text || '', ...opts })];
  }
  return [new TextRun({ text: item.text || '', ...opts })];
}

// 表格之後補一個小間距段落，避免表格緊貼下一段文字。
function spacerAfterBlock() {
  return new Paragraph({
    children: [new TextRun({ text: ' ', size: 8 })],
    spacing: { before: 0, after: 60 },
  });
}

const CELL_MARGINS = { top: 80, bottom: 80, left: 120, right: 120 };

function tableBorders() {
  const line = { style: BorderStyle.SINGLE, size: 4, color: THEME.tableBorder };
  return {
    top: line,
    bottom: line,
    left: line,
    right: line,
    insideHorizontal: line,
    insideVertical: line,
  };
}

function alignFromToken(align) {
  if (align === 'center') return AlignmentType.CENTER;
  if (align === 'right') return AlignmentType.RIGHT;
  return AlignmentType.LEFT;
}

function blockToDocx(token, depth = 0, state = { h1Seen: 0 }) {
  switch (token.type) {
    case 'heading': {
      const runs = inlineToRuns(token.tokens);
      if (token.depth === 1) {
        state.h1Seen += 1;
        // 第一個 H1 當文件標題；之後的每個「# 部」從新頁開始。
        if (state.h1Seen === 1) {
          return [new Paragraph({ style: 'DocTitle', children: runs })];
        }
        return [
          new Paragraph({
            heading: HeadingLevel.HEADING_1,
            pageBreakBefore: true,
            children: runs,
          }),
        ];
      }
      return [
        new Paragraph({
          heading: HEADING_MAP[token.depth] || HeadingLevel.HEADING_6,
          children: runs,
        }),
      ];
    }

    case 'paragraph':
      return [new Paragraph({ children: inlineToRuns(token.tokens) })];

    case 'list': {
      const out = [];
      const indent = 360 * (depth + 1);
      token.items.forEach((item, i) => {
        let marker;
        if (item.task) {
          marker = item.checked ? '☑ ' : '☐ ';
        } else if (token.ordered) {
          marker = `${(Number(token.start) || 1) + i}. `;
        } else {
          marker = '• ';
        }
        const runs = listItemRuns(item);
        out.push(
          new Paragraph({
            children: [new TextRun({ text: marker, color: THEME.accent, bold: token.ordered }), ...runs],
            indent: { left: indent, hanging: token.ordered ? 280 : 200 },
            spacing: { after: 60 },
          }),
        );
        // Handle nested blocks inside the item beyond the first text node.
        if (item.tokens) {
          for (let j = 1; j < item.tokens.length; j++) {
            const nested = blockToDocx(item.tokens[j], depth + 1, state);
            for (const n of nested) out.push(n);
          }
        }
      });
      return out;
    }

    case 'table': {
      const aligns = token.align || [];
      const rows = [];
      const headerCells = (token.header || []).map(
        (h, col) =>
          new TableCell({
            children: [
              new Paragraph({
                alignment: alignFromToken(aligns[col]),
                spacing: { before: 0, after: 0 },
                children: inlineToRuns(h.tokens, { bold: true, color: 'FFFFFF' }),
              }),
            ],
            shading: { fill: THEME.accent },
            margins: CELL_MARGINS,
            verticalAlign: VerticalAlign.CENTER,
          }),
      );
      rows.push(new TableRow({ children: headerCells, tableHeader: true }));
      (token.rows || []).forEach((r, ri) => {
        const banded = ri % 2 === 1; // 第 2、4、6…列上淺色網底
        const cells = r.map(
          (c, col) =>
            new TableCell({
              children: [
                new Paragraph({
                  alignment: alignFromToken(aligns[col]),
                  spacing: { before: 0, after: 0 },
                  children: inlineToRuns(c.tokens),
                }),
              ],
              shading: banded ? { fill: THEME.tableBand } : undefined,
              margins: CELL_MARGINS,
              verticalAlign: VerticalAlign.CENTER,
            }),
        );
        rows.push(new TableRow({ children: cells }));
      });
      return [
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          borders: tableBorders(),
          rows,
        }),
        spacerAfterBlock(),
      ];
    }

    case 'code': {
      // 用單格表格當「程式碼盒」：淺底、細框，行距緊湊，等寬字型。
      const lines = (token.text || '').split('\n');
      const paras = lines.map(
        (line) =>
          new Paragraph({
            children: [new TextRun({ text: line || ' ', font: MONO_FONT, size: 18 })],
            spacing: { before: 0, after: 0 },
          }),
      );
      const line = { style: BorderStyle.SINGLE, size: 4, color: THEME.codeBorder };
      return [
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          borders: {
            top: line, bottom: line, left: line, right: line,
            insideHorizontal: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
            insideVertical: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
          },
          rows: [
            new TableRow({
              children: [
                new TableCell({
                  children: paras,
                  shading: { fill: THEME.codeBg },
                  margins: { top: 120, bottom: 120, left: 160, right: 160 },
                }),
              ],
            }),
          ],
        }),
        spacerAfterBlock(),
      ];
    }

    case 'blockquote': {
      // 引言：左側深藍色邊條＋淺色底＋縮排。內含的表格、清單原樣縮排傳遞。
      const out = [];
      for (const sub of token.tokens || []) {
        if (sub.type === 'paragraph') {
          out.push(
            new Paragraph({
              children: inlineToRuns(sub.tokens, { color: '404040' }),
              indent: { left: 240 },
              spacing: { after: 80 },
              border: {
                left: { style: BorderStyle.SINGLE, size: 18, color: THEME.accent, space: 8 },
              },
              shading: { fill: THEME.quoteBg },
            }),
          );
        } else {
          const blocks = blockToDocx(sub, depth + 1, state);
          for (const b of blocks) out.push(b);
        }
      }
      return out;
    }

    case 'hr':
      return [
        new Paragraph({
          children: [],
          spacing: { before: 120, after: 240 },
          border: {
            bottom: { style: BorderStyle.SINGLE, size: 6, color: THEME.rule },
          },
        }),
      ];

    case 'space':
      return [];

    case 'html': {
      const text = (token.text || '').trim();
      if (!text) return [];
      // Skip pure HTML tags but keep inner text if any.
      const stripped = text.replace(/<[^>]+>/g, '').trim();
      if (!stripped) return [];
      return [
        new Paragraph({
          children: [new TextRun({ text: stripped, italics: true, color: THEME.muted })],
        }),
      ];
    }

    default:
      if (token.text) {
        return [new Paragraph({ children: [new TextRun({ text: token.text })] })];
      }
      return [];
  }
}

function buildStyles() {
  const headingBase = { keepNext: true, keepLines: true };
  return {
    default: {
      document: {
        run: { font: ZH_FONT, size: 21, color: THEME.text }, // 10.5pt 內文
        paragraph: { spacing: { after: 120 } },
      },
    },
    paragraphStyles: [
      {
        id: 'DocTitle',
        name: 'Doc Title',
        basedOn: 'Normal',
        next: 'Normal',
        run: { size: 44, bold: true, color: THEME.accent }, // 22pt 文件標題
        paragraph: {
          spacing: { before: 120, after: 240 },
          border: {
            bottom: { style: BorderStyle.SINGLE, size: 12, color: THEME.accent, space: 6 },
          },
        },
      },
      {
        id: 'Heading1',
        name: 'Heading 1',
        basedOn: 'Normal',
        next: 'Normal',
        quickFormat: true,
        run: { size: 32, bold: true, color: THEME.accent }, // 16pt「第 X 部」
        paragraph: {
          ...headingBase,
          spacing: { before: 240, after: 200 },
          border: {
            bottom: { style: BorderStyle.SINGLE, size: 8, color: THEME.accent, space: 4 },
          },
        },
      },
      {
        id: 'Heading2',
        name: 'Heading 2',
        basedOn: 'Normal',
        next: 'Normal',
        quickFormat: true,
        run: { size: 28, bold: true, color: THEME.accent },
        paragraph: { ...headingBase, spacing: { before: 280, after: 140 } },
      },
      {
        id: 'Heading3',
        name: 'Heading 3',
        basedOn: 'Normal',
        next: 'Normal',
        quickFormat: true,
        run: { size: 26, bold: true, color: THEME.accentSoft }, // 13pt 章標題
        paragraph: { ...headingBase, spacing: { before: 260, after: 120 } },
      },
      {
        id: 'Heading4',
        name: 'Heading 4',
        basedOn: 'Normal',
        next: 'Normal',
        quickFormat: true,
        run: { size: 23, bold: true, color: '2D3748' },
        paragraph: { ...headingBase, spacing: { before: 200, after: 100 } },
      },
      {
        id: 'Heading5',
        name: 'Heading 5',
        basedOn: 'Normal',
        next: 'Normal',
        run: { size: 21, bold: true, color: THEME.muted },
        paragraph: { ...headingBase, spacing: { before: 160, after: 80 } },
      },
      {
        id: 'Heading6',
        name: 'Heading 6',
        basedOn: 'Normal',
        next: 'Normal',
        run: { size: 21, bold: true, italics: true, color: THEME.muted },
        paragraph: { ...headingBase, spacing: { before: 160, after: 80 } },
      },
    ],
  };
}

function buildFooter(title) {
  return new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 0 },
        border: {
          top: { style: BorderStyle.SINGLE, size: 4, color: THEME.rule, space: 4 },
        },
        children: [
          new TextRun({ text: `${title}　·　`, size: 16, color: THEME.muted }),
          new TextRun({ children: ['第 ', PageNumber.CURRENT, ' 頁／共 ', PageNumber.TOTAL_PAGES, ' 頁'], size: 16, color: THEME.muted }),
        ],
      }),
    ],
  });
}

async function convertFile(mdPath, docxPath) {
  const md = await fs.readFile(mdPath, 'utf-8');
  const tokens = marked.lexer(md);
  const state = { h1Seen: 0 };
  const blocks = tokens.flatMap((t) => blockToDocx(t, 0, state));
  const title = path.basename(mdPath, '.md');
  const doc = new Document({
    creator: 'TalentHub docs converter',
    title,
    styles: buildStyles(),
    sections: [
      {
        properties: {
          page: {
            margin: { top: 1134, bottom: 1134, left: 1247, right: 1247 }, // 約 2 公分邊界
          },
        },
        footers: { default: buildFooter(title) },
        children: blocks,
      },
    ],
  });
  const buf = await Packer.toBuffer(doc);
  await fs.writeFile(docxPath, buf);
  return buf.length;
}

async function main() {
  const files = await fs.readdir(SRC_DIR);
  const mds = files.filter((f) => f.startsWith('TalentHub_') && f.endsWith('.md')).sort();
  if (mds.length === 0) {
    console.log('No TalentHub_*.md files found in', SRC_DIR);
    return;
  }
  console.log(`Converting ${mds.length} markdown files: ${SRC_DIR} -> ${DOCS_DIR}`);
  console.log('---');
  let totalOut = 0;
  for (const md of mds) {
    const mdPath = path.join(SRC_DIR, md);
    const docxName = md.replace(/\.md$/, '.docx');
    const docxPath = path.join(DOCS_DIR, docxName);
    try {
      const size = await convertFile(mdPath, docxPath);
      totalOut += size;
      const kb = (size / 1024).toFixed(1);
      console.log(`✓ ${md.padEnd(45)} → ${docxName} (${kb} KB)`);
    } catch (err) {
      console.error(`✗ ${md} failed:`, err.message);
      console.error(err.stack);
    }
  }
  console.log('---');
  console.log(`Done. Total output: ${(totalOut / 1024).toFixed(1)} KB`);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
