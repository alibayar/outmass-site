/**
 * Locale variant purity — a locale must be written in the script and regional
 * variant its folder name promises.
 *
 * Why this exists: key-parity and placeholder checks pass happily on text that
 * is in the WRONG variant of the right language. In 0.1.26 three zh strings
 * were written in Traditional characters inside the Simplified locale and only
 * a manual review caught it. 0.1.27 adds pt_BR + pt_PT, where the same trap is
 * wider: the two share a spell-checker and differ mostly in everyday nouns
 * (arquivo/ficheiro, tela/ecrã, usuário/utilizador), so a stray word from the
 * other side reads as sloppy machine translation to a native speaker.
 *
 * zh_TW gets a second, sharper check. Correct characters are the EASY half of
 * a Traditional translation — any converter produces those. What gives away a
 * converted file is mainland vocabulary in Traditional dress: 軟件 instead of
 * 軟體, 資訊 written as 信息, 範本 as 模板. Those pass every character test, so
 * they are matched as terms.
 *
 * The word lists are deliberately small and unambiguous — each entry is a word
 * that is simply not used in the other variant, not a stylistic preference.
 * Matching is whole-word and diacritic-exact for Latin scripts, substring for
 * CJK (which has no word boundaries).
 */

const fs = require("fs");
const path = require("path");

const LOCALES_DIR = path.join(__dirname, "..", "_locales");

// Traditional-only characters that must never appear in a Simplified locale.
// (Simplified forms in parentheses for the next reader.)
const TRADITIONAL_ONLY = [
  "個", // 个
  "們", // 们
  "來", // 来
  "時", // 时
  "會", // 会
  "後", // 后
  "點", // 点
  "發", // 发
  "郵", // 邮
  "電", // 电
  "檔", // 档
  "設", // 设
  "當", // 当
  "從", // 从
  "開", // 开
  "關", // 关
  "訊", // 讯
  "傳", // 传
  "選", // 选
  "應", // 应
];

// Words that exist in exactly one Portuguese variant's everyday register.
const BR_ONLY = [
  "arquivo", "arquivos",
  "tela", "telas",
  "usuário", "usuários",
  "gerenciar", "gerenciamento",
  "configurações",
  "aba", "abas",
  "celular",
  "acessar",
  "salvar",
  "cadastro",
  "time", // BR for "team"; pt-PT says "equipa"
];

const PT_ONLY = [
  "ficheiro", "ficheiros",
  "ecrã", "ecrãs",
  "utilizador", "utilizadores",
  "gerir",
  "definições",
  "separador", "separadores",
  "telemóvel",
  "aceder",
  "guardar",
  "eletrónico", "eletrónica", "eletrónicos",
  "receção",
  "contacto", "contactos",
  "equipa",
  "transferir",
];

// Simplified-only forms that must never appear in the Traditional locale.
//
// Vetted against the real zh_TW file: characters that merely LOOK Simplified
// but are standard Traditional too are deliberately absent — 回 (回覆),
// 系 (系統), 准 (核准), 台, 里, 西. Including them produced only false alarms.
const SIMPLIFIED_ONLY = (
  "个们来时会后点发邮电档设当从开关讯传选应为这说软网数复过帐" +
  "爱边参产称达带单东动对队丰夫盖给观规号护划欢环还汇获击级际济继" +
  "价见将讲奖节结进举据觉克库块历丽联两临领龙楼录虑轮论罗马买卖满" +
  "门梦灭难脑内宁农齐启气钱强轻庆穷区权劝却让热认荣润伤审胜师实识" +
  "势试适释书术树双谁顺丝虽随孙态谈汤糖体条铁听厅统头图团退伟卫问" +
  "务习细现线乡响项写谢兴须严样养业页义议异艺亿忆营优鱼与语预园员" +
  "远愿约跃运杂灾载赞脏责则贼战长张争证织执职纸质终种众专转装状资总组筛"
).split("");

// Mainland vocabulary written in TRADITIONAL characters — the tell of a
// converted file rather than a real Taiwan translation. Character checks
// cannot catch these, which is the whole reason this list exists.
// Multi-character terms only. A bare word that is legitimate in Taiwan in
// another sense (主題 = topic) or that collides as a substring with innocent
// text (定時 inside 指定時間) is matched in its full mainland form instead.
const MAINLAND_TERMS = [
  ["軟件", "軟體"],
  ["信息", "資訊"],
  ["數據", "資料"],
  ["模板", "範本"],
  ["服務器", "伺服器"],
  ["網絡", "網路"],
  ["設置", "設定"],
  ["視頻", "影片"],
  ["收件人", "收件者"],
  ["登錄", "登入"],
  ["註銷", "登出"],
  ["缺省", "預設"],
  ["默認", "預設"],
  ["激活", "啟用"],
  ["營銷", "行銷"],
  ["賬戶", "帳戶"],
  ["賬號", "帳號"],
  ["郵箱", "信箱"],
  ["回复", "回覆"],
  ["定時傳送", "排程傳送"],
  ["定時發送", "排程傳送"],
  ["郵件主題", "郵件主旨"],
  ["技術支持", "技術支援"],
  ["優先支持", "優先支援"],
  ["應用程序", "應用程式"],
];

// locale dir -> rules
const RULES = {
  zh: { chars: TRADITIONAL_ONLY, label: "Traditional characters in a Simplified locale" },
  zh_CN: { chars: TRADITIONAL_ONLY, label: "Traditional characters in a Simplified locale" },
  zh_TW: {
    chars: SIMPLIFIED_ONLY,
    label: "Simplified characters in the Traditional locale",
    terms: MAINLAND_TERMS,
  },
  pt_BR: { words: PT_ONLY, label: "European Portuguese word in the Brazilian locale" },
  pt_PT: { words: BR_ONLY, label: "Brazilian Portuguese word in the European locale" },
};

// Words inside these constructs are code/brand, not prose.
function strippable(message) {
  return String(message)
    .replace(/\{\{[^}]*\}\}/g, " ") // merge tags
    .replace(/\$[A-Za-z0-9_]+\$/g, " ") // named placeholders
    .replace(/<[^>]+>/g, " "); // html tags
}

function run() {
  const failures = [];

  for (const [loc, rule] of Object.entries(RULES)) {
    const file = path.join(LOCALES_DIR, loc, "messages.json");
    if (!fs.existsSync(file)) continue; // locale not shipped (yet)

    let msgs;
    try {
      msgs = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch (e) {
      failures.push(`${loc}: messages.json unparseable — ${e.message}`);
      continue;
    }

    for (const [key, entry] of Object.entries(msgs)) {
      const text = strippable(entry && entry.message);

      if (rule.chars) {
        for (const ch of rule.chars) {
          if (text.includes(ch)) {
            failures.push(`${loc}: key "${key}" contains "${ch}" — ${rule.label}`);
          }
        }
      }

      if (rule.terms) {
        for (const [mainland, taiwan] of rule.terms) {
          if (text.includes(mainland)) {
            failures.push(
              `${loc}: key "${key}" uses mainland term "${mainland}" — ` +
              `Taiwan writes "${taiwan}" (Traditional characters alone are ` +
              `not enough; this is what a converted file looks like)`
            );
          }
        }
      }

      if (rule.words) {
        const lower = text.toLowerCase();
        for (const w of rule.words) {
          // Whole word: not part of a longer token. Portuguese letters only.
          const re = new RegExp(
            `(^|[^0-9a-záàâãéêíóôõúüç])${w}($|[^0-9a-záàâãéêíóôõúüç])`,
            "i"
          );
          if (re.test(lower)) {
            failures.push(`${loc}: key "${key}" uses "${w}" — ${rule.label}`);
          }
        }
      }
    }
  }

  return { name: "locale-variants", failures };
}

module.exports = { run };
