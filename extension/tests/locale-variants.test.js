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
 * The word lists are deliberately small and unambiguous — each entry is a word
 * that is simply not used in the other variant, not a stylistic preference.
 * Matching is whole-word and diacritic-exact.
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

// locale dir -> { forbidden: [words], label }
const RULES = {
  zh: { chars: TRADITIONAL_ONLY, label: "Traditional characters in a Simplified locale" },
  zh_CN: { chars: TRADITIONAL_ONLY, label: "Traditional characters in a Simplified locale" },
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
