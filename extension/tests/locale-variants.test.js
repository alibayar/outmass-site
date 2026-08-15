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

// Turkish stripped of its own letters. On 2026-08-13 sixty-seven strings in
// the tr locale read "gonder", "buyuk", "Arsivle", "Onizleme" — the file was
// half properly written and half typed on a keyboard that could not produce
// ç ğ ı ö ş ü, which to a Turkish reader is the difference between a product
// and a machine translation of one. Key parity and placeholder checks passed
// on every one of them.
//
// Every entry is a word that is ONLY ever the stripped form of a Turkish word
// — never a correct spelling. Deliberately not exhaustive: a list with one
// false positive gets deleted, and a list with sixty true positives does the
// job. Notably absent, having caught the author out: limitleri, indir,
// geldin, ileri, geri, bitir — all correct Turkish that happens to need no
// special letter.
const TR_ASCII_STRIPPED = [
  "gonder", "gonderim", "gonderilecek", "gondermek", "gondermeye", "gonderildi",
  "gonderir", "gonderici", "gunluk", "gunde", "gunlere", "buyuk", "kucuk",
  "sutun", "arsiv", "arsivle", "arsivli", "arsivden", "onizleme", "yukselt",
  "yukseltme", "simdi", "basarili", "basarisiz", "alici", "aliciya", "alicilar",
  "icin", "icerik", "icerigi", "kisisel", "kisisellestirmek", "olustur",
  "duzenle", "sablon", "baslamak", "secin", "cikis", "giris", "gorunuyor",
  "gorunur", "gormek", "aciklama", "dogru", "yukle", "yukleyin", "kaldirildi",
  "atlandi", "tarayici", "arayuz", "ozellik", "surede", "donuk", "iletisim",
  "sinirlamasi", "kisitli", "gecerli", "itibarinizi", "asamaz", "yavaslatir",
  "isaretlenmesini", "soguk", "birkac", "adim", "kisaltilmis", "kapatilmamis",
  "olasi", "farkli", "virgulle", "ayrilmis", "dosyayi", "ulasilamiyor",
  "baglanti", "baglantinizi", "guvenlik", "duvarinizi", "ustundeki",
  "hesapsiz", "istege", "kullanilamaz", "adinda", "kampanyayi", "olmali",
  "fransizca", "ispanyolca", "rusca", "arapca", "hintce", "muduru", "yazilim",
  "satis", "kotamiz", "hesaplari", "kotanizda", "hakkiniz", "yalnizca",
  "aninda", "kilar", "hakkinda", "ceyrek", "dusebilir", "takilmamak", "hos",
  "tumunu", "ornek",
];

// The same defect class shipped again nine days after the Turkish fix, in
// three more languages, because this mechanism was wired to tr alone. Same
// doctrine as TR_ASCII_STRIPPED: every entry is a word that actually
// occurred stripped in the file, and a word that is correct WITHOUT its
// accent in some other reading never gets in — es "continua" (the feminine
// adjective is accentless) was found as a defect and still kept out of this
// list for exactly that reason. fr "boite"/"parait" are deliberately IN:
// the 1990 rectifications allow them, this product's convention does not.
// The review's second pass then pruned these lists by the same doctrine it
// audited them with: es campana/campanas (a bell), mas (poetry-register
// 'but'), limite/limites (subjunctive of limitar), and five bare futures
// (cobrara/enviara/enviaran/funcionaran/tardara read as correct
// preterite-subjunctives without the accent) are all real Spanish words in
// SOME reading; fr supprimes (tu supprimes) likewise; de gross/grosse/
// grossen/grossbuchstaben are correct Swiss Standard German, which has no ß
// and shares this generic de/ folder — the list already excluded "aussen"
// on exactly that ground. fr deliverabilite/retroaction left because their
// base words were themselves wrong and got fixed, so the stripped form no
// longer names anything. The strings all these were written for are fixed;
// what remains is only entries that can never fire falsely.
const DE_ASCII_STRIPPED = [
  "ausloesen", "empfaenger", "enthaelt", "franzoesisch", "fuer",
  "geschaeftsfuehrer",
  "hoechstens", "koennen", "koennte", "kuerzlich", "laeuft", "moegliche",
  "mueller", "naechsten", "oberflaechensprache", "persoenlich", "pruefen",
  "rueckblickzeitraum", "schaltflaeche", "schuetzen", "taegliche", "ueber",
  "ueberschreiben", "ueberschreibt", "ueberspringen", "uebersprungen",
  "uebrig", "waehlen", "woerter", "zurueck", "zusaetzlich",
];

const FR_ASCII_STRIPPED = [
  "apercu", "archivees", "arriere", "boite", "caracteres", "declencher",
  "deja", "delimite", "delivrabilite", "desarchiver",
  "detectes", "difference", "echoue", "ecrire", "egalement", "envoye",
  "envoyes", "etalez", "etape", "etes", "etre", "evite", "expediteur",
  "fenetre", "francais", "general", "immediatement", "malgre", "meme",
  "necessite", "nommee", "parait", "periode", "premiere", "probleme",
  "protege", "proteger", "recente", "reception", "recurrents", "rediger",
  "reessayez", "reputation", "reussie",
  "telecharger", "telechargez", "verifiez",
];

const ES_ASCII_STRIPPED = [
  "actualizacion", "ademas", "aleman", "arabe", "atras", "automaticamente",
  "automatico", "boton", "busqueda",
  "conexion", "dia", "dias", "direccion", "envia",
  "envio", "espanol", "extension", "frances", "frias", "funcion",
  "garcia", "imagenes", "japones",
  "lopez", "martinez", "maximo", "mayusculas", "moscu", "movil",
  "pestana", "reputacion", "sesion", "tambien",
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
  tr: {
    asciiWords: TR_ASCII_STRIPPED,
    label: "Turkish written without its own letters (ç ğ ı ö ş ü)",
  },
  de: {
    asciiWords: DE_ASCII_STRIPPED,
    label: "German written as ASCII transliteration (ue/oe/ae/ss for ü ö ä ß)",
  },
  fr: {
    asciiWords: FR_ASCII_STRIPPED,
    label: "French written without its accents (é è ê à ç î ô û)",
  },
  es: {
    asciiWords: ES_ASCII_STRIPPED,
    label: "Spanish written without its accents (á é í ó ú ñ ü)",
  },
};

/**
 * Pure-ASCII words in a message, with addresses and URLs removed first.
 *
 * `eposta@ornek.com` and `ayse@example.com` are the placeholder address and
 * the sample CSV row: their local parts must stay ASCII, and reading them as
 * prose would flag two strings that are exactly right.
 *
 * A word carrying a Turkish letter cannot survive the [A-Za-z]+ tokeniser
 * intact — "Gönder" arrives as "G" and "nder" — so a correct string simply
 * has nothing for the list to match, provided no entry is a fragment.
 */
function asciiWords(text) {
  return String(text)
    // Bounded to an address shape, not \S+@\S+: the greedy form swallowed
    // everything to the next SPACE, so in a CSV template row
    // ("klaus@example.com,Klaus,Mueller,…") it ate the very names the
    // tripwire was written to protect. Found by the 0.2.2 release review.
    .replace(/[^\s,;]+@[^\s,;]+/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .match(/[A-Za-z]{3,}/g) || [];
}

// Words inside these constructs are code/brand, not prose.
function strippable(message) {
  return String(message)
    .replace(/\{\{[^}]*\}\}/g, " ") // merge tags
    .replace(/\$[A-Za-z0-9_]+\$/g, " ") // named placeholders
    .replace(/<[^>]+>/g, " "); // html tags
}

function run() {
  const failures = [];
  const check = (ok, msg) => { if (!ok) failures.push(msg); };

  // ── The Turkish matcher, self-tested before it is trusted ──
  //
  // The first version of this detector was written in Python with a
  // case-insensitive regex and reported all sixty-seven CORRECTED strings as
  // still broken: under case folding `ı` and `i` are equivalent, because
  // "ı".toUpperCase() is "I". JavaScript's /i/ flag does not fold them, but
  // relying on that silently is how the same hour gets spent twice.
  const has = (text, word) => asciiWords(text).some((w) => w.toLowerCase() === word);
  check(has("Test Gonder", "gonder"), "the Turkish matcher no longer sees a stripped word");
  check(!has("Test Gönder", "gonder"), "the Turkish matcher flags correctly written Turkish");
  check(!has("eposta@ornek.com", "ornek"), "the Turkish matcher reads an email address as prose");
  // The matcher reports whatever is in the list, so the only defence against a
  // false positive is the list itself. These six are correct Turkish that
  // needs no special letter, and every one of them was flagged by the first
  // draft of this word list.
  check(
    !TR_ASCII_STRIPPED.some((w) => ["limitleri", "indir", "geldin", "ileri", "geri", "bitir"].includes(w)),
    "a correctly-spelled Turkish word got into TR_ASCII_STRIPPED — one false " +
      "positive and the next person deletes the whole suite"
  );

  // The three languages added 2026-08-15, each proven the same way: the
  // matcher must fire on a planted stripped string and stay silent on the
  // correctly-written one.
  check(has("Empfaenger pruefen", "empfaenger"), "the German matcher no longer sees a transliterated word");
  check(!has("Empfänger prüfen", "empfaenger"), "the German matcher flags correctly written German");
  check(has("Verifiez avant envoi", "verifiez"), "the French matcher no longer sees a stripped word");
  check(!has("Vérifiez avant envoi", "verifiez"), "the French matcher flags correctly written French");
  check(has("esta campana", "campana"), "the Spanish matcher no longer sees a stripped word");
  check(!has("esta campaña", "campana"), "the Spanish matcher flags correctly written Spanish");
  // List hygiene, same doctrine as the Turkish six: words that are correct
  // in that language WITHOUT the accent in some reading must never enter
  // the list. "continua" is the proven case — it occurred stripped as a
  // verb (continúa) and was fixed, but the feminine adjective is accentless
  // ("línea continua"), so the tripwire cannot carry it.
  check(
    !ES_ASCII_STRIPPED.some((w) => [
      "continua", "campana", "campanas", "mas", "limite", "limites",
      "cobrara", "enviara", "enviaran", "funcionaran", "tardara",
    ].includes(w)),
    "es: a word that is correct WITHOUT its accent in some reading got " +
      "into the list — one false positive and the suite loses its trust"
  );
  check(
    !DE_ASCII_STRIPPED.some((w) => [
      "neue", "dauer", "muss", "dass", "aussen", "adresse",
      "gross", "grosse", "grossen", "grossbuchstaben",
    ].includes(w)),
    "de: a legitimate ue/ss word (or a Swiss Standard German ss form) got " +
      "into the transliteration list"
  );
  check(
    !FR_ASCII_STRIPPED.some((w) => ["envoyez", "des", "les", "active", "avec", "supprimes"].includes(w)),
    "fr: an accentless-correct French word got into the list"
  );
  // The scrubber must stop at CSV separators or the template rows escape
  // the sweep entirely — while still reading a whole address as one blob.
  check(!has("eposta@ornek.com", "ornek"), "the scrubber still swallows a full address");
  check(has("klaus@example.com,Klaus,Mueller,GmbH", "mueller"),
    "the scrubber no longer eats the CSV fields after an address");

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

      if (rule.asciiWords) {
        const seen = new Set(asciiWords(text).map((w) => w.toLowerCase()));
        for (const w of rule.asciiWords) {
          if (seen.has(w)) {
            failures.push(
              `${loc}: key "${key}" uses "${w}" — ${rule.label}. ` +
              `Write it with the letter it needs; the text otherwise reads ` +
              `as a machine translation to a native speaker`
            );
          }
        }
      }
    }
  }

  return { name: "locale-variants", failures };
}

module.exports = { run };
