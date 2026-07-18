# Pazarlama Yol Haritası — Taslak (sıfırdan beyin fırtınası, 2026-07-19)

> **Not (oku):** Bu belge kasıtlı olarak *taze gözle* yazıldı — önceki pazarlama notları, MEMORY dosyaları ve eski planlar **okunmadan** hazırlandı. Amaç, mevcut varsayımlara demir atmadan sıfırdan bir bakış üretmek. Finalize etmeden önce mevcut notlarla (MEMORY, önceki growth/GEO çalışmaları, blog envanteri) **uzlaştırılacak**; olası çakışmalar ve zaten yapılmış işler o aşamada elenecek.
>
> **Sabit kural:** Pazarlama yalnızca **canlı olan** özellikleri iddia eder (CSV merge + {{tag}}, açılma/tık takibi, yanıt tespiti, zamanlı gönderim, günlük gönderim limiti, otomatik takipler (Pro), A/B konu testi, AI yazar, OneDrive paylaşım linki ekleri, kayıtlı şablonlar, 11 dil UI). Henüz olmayan hiçbir yetenek yazıya girmez.
>
> **Bağlam:** Solo kurucu + AI. En kıt kaynak = **kurucunun zamanı**. Baz bütçe $0, gerekçelendirilirse ~$200/ay deneysel harcama. ~5 ödeyen müşteri, düzinelerce kurulum, PMF öncesi. Değerlendirme üç jüriden geldi: **founder-reality** (solo kurucuya uyum), **icp-fit** (gerçek alıcıya ulaşım), **compounding** (kalıcı varlık biriktirme).

---

## Şimdi (0–30 gün)

Tema: **Kur bir kez, sonsuza dek işlesin.** Hepsi S efor, $0, kurucunun sürekli ilgisini istemeyen, birbirini besleyen temeller. Üç jürinin de en yüksek ortak puanları burada.

### Ana öneri

**1. Mağaza listeleme revizyonu — tek oturumda (başlık + kategori + demo video)**
Chrome Web Store ve Edge Add-ons aramasında başlık ve ilk satırlar keyword eşleşmesinde ağır basar; "GMass for Outlook" boşluğu neredeyse rakipsiz. Aynı oturumda kategoriyi de gerçek mail-merge/tracking rakiplerinin bulunduğu yere taşı ve ilk 2 ekran görüntüsünü "billboard"a çevirip 30 sn'lik gerçek merge-gönder demo videosu ekle.
`Efor: S · Maliyet: $0 · Sinyal: 1–2 hafta (mağaza arama sırası + install conversion)`
İlk adım: Başlığı tek ana ifadeye çıpala — **"Mail Merge for Outlook"** — "GMass alternative"i açıklama gövdesine koy (keyword-stuffing reddini önlemek için). Slide #2'yi ispatlanabilir gizlilik satırıyla aç: **"E-postalar sunucularımıza asla uğramaz."**

**2. Bing Webmaster + IndexNow → Copilot pipeline (bir kerelik altyapı)**
getoutmass.com'u Bing Webmaster'da doğrula, IndexNow'ı deploy adımına tek API ping olarak bağla. Bu, sonraki her sayfanın **günler içinde** (aylar değil) indekslenmesini sağlar — tüm içerik varlıklarının time-to-value'sunu hızlandıran boru hattı. Bing indeksi Copilot'un web-grounded cevaplarını besler; ICP zaten Edge/Bing/M365 içinde.
`Efor: S · Maliyet: $0 · Sinyal: 2–4 hafta`
İlk adım: Bugün Bing Webmaster'a kaydol + sitemap gönder, deploy'a tek IndexNow ping ekle. **Bing sırası** ile **Copilot atıfı**nı iki ayrı haftalık metrik olarak logla — sıralama kazanımı atıf kazanımıyla karıştırılmasın.

**3. Tek kanonik "AI-alıntılanabilir gerçekler/specs" sayfası**
Atomik, alıntılanabilir gerçeklerden oluşan tek yoğun sayfa ("Ücretsiz plan: 250 e-posta/ay", "warm-up için günlük gönderim limiti mevcut" vb.), her biri kendine yeten deklaratif cümle, FAQPage JSON-LD ile işaretli. Hem featured-snippet hedefi hem de cevap-motoru (Perplexity/ChatGPT/Copilot) atıf kaynağı. **Diğer tüm SEO/mağaza/forum çalışmalarının link geri döndüğü kanonik URL** olur — otorite tek sayfada toplanır.
`Efor: S · Maliyet: $0 · Sinyal: 4–6 hafta (indeksleme); manuel promptlarla daha erken kontrol edilebilir`
İlk adım: Sayfayı FAQPage şemasıyla yayınla, 5 birebir soruyu ("outlook mail merge günlük limit ne", "ücretsiz outlook mail merge var mı") ChatGPT/Perplexity/Copilot'ta öncesi/sonrası test et, atıfları logla. Yalnızca canlı özellikleri yaz.

**4. "GMass for Outlook / GMass alternative Outlook" yakalama sayfası**
Neredeyse sıfır rekabetli, OutMass'ın kimliğiyle birebir eşleşen sorgu kümesi: GMass'ın Outlook'ta çalışmadığını arayan / muadil isteyen kullanıcı zaten kendini "ödeyen araç alıcısı" olarak nitelemiş. Listedeki en yüksek niyetli trafik.
`Efor: S · Maliyet: $0 · Sinyal: 2–4 hafta`
İlk adım: H1 + ilk paragraf birebir cevap versin: **"Hayır, GMass Outlook ile çalışmaz — işte Outlook-native alternatif"** + canlı yan yana "GMass Outlook'u desteklemiyor, işte destekleyen" tablosu. Bing/Google URL inspection ile anında tarama iste. Bu sayfayı **her comparison blog yazısının iç-link hedefi** yap.

### Alternatifler (0–30 gün, ikincil ama hâlâ ucuz/hızlı)

- **"How to mail merge in Outlook on the web" snippet-format eğitimi** — Ürünün en yüksek-niyetli literal sorgusu; OutMass tek amaca-özel araç. İlk 150 kelimede 5–7 adımlık numaralı liste (pazarlama metninden önce), adım başına 1 gerçek ekran görüntüsü. `Efor: S · $0 · 3–6 hafta.` İlk adım: Yayınla, Bing URL submission, haftalık snippet kontrolü. *Not: AI Overviews tık olmadan cevap sentezleyebilir — impression değil gerçek tık izle.*
- **M365 günlük gönderim-limiti hesaplayıcı (ücretsiz mini-araç)** — Lisans tipini seç → güvenli günlük/saatlik limit + warm-up ramp; canlı Günlük Gönderim Limiti özelliğine CTA. Cold-sender'ların throttling kaygısını cevaplar, doğal olarak linklenebilir/alıntılanabilir. `Efor: S · $0 · 4–8 hafta organik.` İlk adım: Build'i 1 günle sınırla; önce 3–5 mevcut forum thread'ine ("O365'ten günde kaç mail gönderebilirim") cevap+link koy, dağıtımı test et. Her sonuç "bunu OutMass'te Günlük Limit olarak ayarla" CTA'sıyla bitsin.
- **Reddit & Quora'daki mevcut "GMass for Outlook?" talebini hasat et** — Bu thread'ler senin kelimelerinle yazılmış talep. Açıklamalı (affiliation disclosed), gerçekten yardımcı cevap. `Efor: S · $0 · günler (etkileşim), 1–2 hafta (kayıt).` İlk adım: Son 24 ayda "GMass Outlook" + "mail merge outlook web" ara, 10 canlı thread'e tek oturumda UTM-linkli cevap. r/sysadmin, r/microsoft365, r/coldemail'i (bütçe sahibi M365 org'ları) önceliklendir. *Not: no-self-promo sub'ları atla, disclosure şart.*
- **Manuel mağaza-yorumu isteği (5 ödeyen müşteriye)** — In-product nudge inşa etmeden önce, mevcut ~5 ödeyen müşteriye tek-tık yorum linkiyle kişisel e-posta gönder. Yorum tabanı hem mağaza sıralamasını hem install-güvenini kalıcı besler. `Efor: S · $0 · 1–2 hafta.` İlk adım: E-postaları gönder, mağaza politikasında teşvikli-yorum kuralını kontrol et, dönüşümü ölç — istekliliği doğrula.
- **Mağaza listelemesini mevcut kullanıcı locale'lerine çevir (NL + CN önce)** — Extension zaten 11 dilde; çeviri varlıklarını mağaza başlık/açıklama/caption alanlarına yapıştır. Rakipler İngilizce/Gmail-first, non-İngilizce mağaza araması rakipsiz. `Efor: S · $0 · 3–4 hafta.` İlk adım: Sadece NL ve CN'yi doldur, o locale'lerin install sayısını öncesi/sonrası karşılaştır. Release checklist'e "listeleme çevirisini güncelle" ekle (drift olmasın).

---

## Sıradaki (30–90 gün)

Tema: **İçerik merdiveni + talep yakalama.** Temel oturunca compounding varlıklar biriktir; birkaç ölçülü ücretli deney başlat.

### Ana öneri

**1. Long-tail "mail merge in Outlook" YouTube eğitim merdiveni**
Her biri tek birebir sorguyu hedefleyen sıkı 5–8 dk ekran-kaydı eğitimler ("mail merge outlook web csv", "outlook mail merge without word"), başlık = sorgu birebir. GMass/YAMM Gmail-eğitim sonuçlarına sahip; Outlook-web versiyonunu neredeyse kimse yapmamış. "Eğitim" = zaten sevk edilmiş ürünü anlatmak, ayrı üretim hattı yok.
`Efor: M · Maliyet: $0 · Sinyal: 2–4 hafta`
İlk adım: En yüksek-niyetli tek sorguya video çek, getoutmass.com landing'e göm, YouTube Studio + site referral'ı izle. Her videoyu eşleşen how-to/comparison sayfasına da göm — video ve sayfa birbirinin sıralamasını besler.

**2. Gerçek indirilebilir mail-merge şablon galerisi (2 tohum)**
Şablonlar doğal olarak paylaşılabilir/bookmarklanabilir — bootstrap kurucuya sıfır-outreach organik backlink yolu, ayrıca ayrı bir sorgu kümesi ("cold email csv template"). Gerçek {{tag}} sözdizimi + "open in OutMass" CTA.
`Efor: M · Maliyet: $0 · Sinyal: 4–8 hafta`
İlk adım: Sadece 2 şablon (recruiter + sales follow-up — zaten ödeyen kullanıcı olan iki segment), her biri kurucunun gerçek gözden geçirmesinden geçmiş. İndirmeleri/CTA tıklarını izle, ancak backlink alırlarsa büyüt.

**3. Günlük gönderim limitini r/coldemail'de deliverability düşünce-liderliğine çevir**
M365 throttling/reputation mekaniğini asıl madde yap, canlı Günlük Gönderim Limiti özelliğini örnek olarak kullan (pitch değil). Reddit thread'leri yıllarca Google'da sıralanır **ve** AI cevap-motorlarının retrieval/eğitim verisinde orantısız yer alır — yazıldıktan sonra da OutMass'ı yüzeye çıkarmaya devam eder.
`Efor: S · Maliyet: $0 · Sinyal: 1–2 hafta`
İlk adım: r/coldemail + r/Emailmarketing'e eğitici post, upvote oranı ve "bu hangi araç?" organik sorusunu izle. Aynı özü site-içi send-limit hesaplayıcıya taşı ve ikisini linkle — sosyal spike kalıcı bir varlığa yatırılsın.

**4. r/sysadmin için IT-onay tek sayfalık brief**
Gerçek M365 org'larında satış/recruiting personeli Graph-scoped extension'ı IT onayı olmadan kuramaz — rakiplerin görmezden geldiği gerçek adopsiyon engeli. Tam Graph scope'ları (Mail.Send/Mail.Read, delegated değil application, sunucu-tarafı e-posta saklama yok) doğrulanabilir "sunucularımıza uğramaz" mimarisiyle bu şüpheci kitleye hitap eder. Bir onaylayan admin tüm takımı açar.
`Efor: M · Maliyet: $0 · Sinyal: 2–4 hafta`
İlk adım: İzin tablolu + **"talep ETMEDİĞİMİZ izinler"** tablolu tek sayfa hazırla, "işte tam olarak neye erişiyoruz, sorun" diye r/sysadmin'e koy. Pazarlama dili = paramparça edilir; acımasızca teknik olsun.

### Alternatifler (30–90 gün)

- **Programmatic long-tail matrisi (önce 3 sayfa)** — Kullanım alanı × Outlook türü (recruiter/agency/sales × personal/M365/web), her biri o kombinasyona özel gerçek adım+ekran görüntüsü. `M · $0 · 6–8 hafta.` İlk adım: Sadece 3 sayfa (recruiter, agency, sales — gerçek kullanıcı olan segmentler), 3 hafta impression izle, sonra genişletmeye karar ver. *Not: helpful-content/doorway riski — hacmi düşük, her sayfa gerçekten farklı tut.*
- **Mağaza listelemesinin tam 11-dil lokalizasyonu** — NL/CN pilotu işe yararsa kalan 9 dile yay. `M · $0 · 3–4 hafta.`
- **In-product yorum nudge (ilk gerçek başarıya bağlı)** — Kampanya açılma/yanıt aldığında küçük, kapatılabilir sidebar yorumu, doğrudan review kutusuna deep-link. `M · $0 · 4–6 hafta.` İlk adım: Manuel versiyonu (yukarıda) önce doğrula, sonra tetikleyiciyi inşa et. *User-facing UX değişikliği — kurucu onayı gerekir; teşvikli-yorum politikasını kontrol et.*
- **Directory submission'ları (AlternativeTo, SaaSHub, Slant, chrome-stats)** — Mevcut comparison yazılarını kaynak alarak self-serve, UTM-linkli. Uzun-vadeli comparison-search SEO ile compound eder. `S–M · $0 · 3–6 hafta.` İlk adım: AlternativeTo (~15 dk). *Ücretli BetaList fast-track ve soğuk listicle-yazar outreach kısmını atla — düşük getiri.*
- **[Ücretli deney] Küçük recruiter/SDR newsletter'da flat-fee slot** — Auction yerine tek async satın alma; sıkı-eşleşmiş niş kitle (3–10k abone), Google/Bing reklamının istediği haftalık optimizasyon yok. `S · $50–150 tek seferlik · 1–2 hafta.` İlk adım: 3–5 aday newsletter'dan open-rate kanıtı iste, en ucuzunu UTM-linkli tek test olarak al. Metinde açık Outlook kancası şart. *Not (compounding): tek-atışlık harcama, kalıcı varlık bırakmaz — organik dönüşen bir sayfa/mesaj kanıtlanınca yap.*
- **[Ücretli deney] Bing/Microsoft Ads exact-match "outlook mail merge" kümesi** — Bing kitlesi Windows/Edge/M365'e self-select; niş CPC düşük, $5/gün top slot'u alabilir. `S · $150–200/ay · 2–3 hafta.` İlk adım: Homepage değil, niyet-eşleşen dedike landing'e yönlendir; cost-per-signup ile yargıla. *Not: hacim çok düşükse istatistiksel anlamlılığa hiç ulaşmayabilir.*
- **[Ücretli deney] Google Ads dar rakip-fetih kampanyası** — Sadece "gmass alternative", "mailmeteor for outlook", "yamm outlook"; generic terimler negatif. `S · ≤$100/ay · 2–4 hafta.` *⚖️ Jüri anlaşmazlığı: icp-fit bunu üst-sıraya koydu (niyet başına en yüksek), founder-reality tuzak dedi (auto-broadening haftalık el-denetimi gerektirir, bütçeyi generic'e sızdırır). Karar: sadece haftalık denetime söz verebilirsen çalıştır, auto-apply'ı kapat.*
- **X / Reddit / LinkedIn saved-search "reply-guy" kurtarma** — "GMass Outlook", "Mailmeteor doesn't work outlook" için kayıtlı aramalar, yardımcı+açıklamalı UTM-linkli cevap. Same-day ship sayesinde "bunu yapıyor mu?" itirazı bir günde gerçekten sevk edilebilir. `S · $0 · günler.` *Not: no-self-promo sub'larından kaçın; UTM ile tık logla.*
- **OutMass'ı sweep listesine outreach kanalı olarak dogfood et** — Outlook mail-merge acısını public paylaşanlardan 20 kişilik el-seçili liste, OutMass üzerinden birebir soru-cevaplayan kişiselleştirilmiş mail; kendi merge/tracking'i canlı ispat. `S · $0 · günler.` İlk adım: 20 kişi, açılma/yanıt izle. *~20 sendte tut, kişisel — yoksa "scrape edilmiş" hissi verir.*
- **[Contrarian] Microsoft'un kendi forumlarını tohumla (rakip yerine)** — answers.microsoft.com / Microsoft Q&A / r/Outlook thread'lerini geçmeye çalışmak yerine, o yüksek-otorite thread'lere gerçekten yardımcı (spam değil) cevap koy, OutMass'ı bir seçenek olarak isimlendir. `S · $0 · thread'de anında görünürlük, 2–6 hafta tık.` *Not: mod'lar self-promo'ya düşman — önce gerçek yardım, affiliation açıkla.*

---

## Sonra (90+ gün)

Tema: **Büyük atışlar — ama ancak temel (SEO varlıkları + yorumlar + trafik) trafiği yakalayıp tutacak hale gelince.** Tek-atışlık spike'lar en sona.

### Ana öneri

**1. Show HN — mimariyle aç, pitch'le değil**
Delegated Graph API send akışını (e-postanın neden OutMass sunucusu yerine kullanıcının kendi M365 hesabından gittiğini) teknik yazı olarak anlat, "Show HN" başlığıyla gönder. "Sunucularımıza uğramaz" burada doğrulanabilir mühendislik gerçeği, HN'in şüpheciliğinden sağ çıkacak türden bir iddia.
`Efor: M · Maliyet: $0 · Sinyal: aynı gün (~4 saatte front page olur ya da olmaz)`
İlk adım: 400 kelimelik teknik açıklayıcı yaz, Salı/Çarşamba ABD sabahı gönder, ilk 3 saat her yorumu kişisel cevapla. Post gövdesinde pricing/CTA dili yok.

**2. Product Hunt — "PH yapmak" değil, sıralı hazırlık**
Sıfır momentumla launch etme. Önce 5 ödeyen müşteriden ilk-saat gerçek kullanım-durumu yorumu için söz al (PH algoritması erken etkileşim kalitesine ağırlık verir), bir güçlü GIF hazırla, sonra tarih seç.
`Efor: M · Maliyet: $0 · Sinyal: 1 gün launch, 2 hafta hazırlık penceresi`
İlk adım: Bu hafta 5 müşteriye ilk-saat yorumu sor, 2 hafta sonrasına tarih koy. *⚖️ Jüri anlaşmazlığı: compounding bunu "erken/tek-atışlık B2C-eğilimli spike" diye tuzak saydı. Karar: farkındalık/backlink olayı olarak gör, growth bahsi değil — ve ancak SEO/mağaza/yorum varlıkları trafiği yakalayacak hale gelince.*

**3. Login'siz ücretsiz mikro-araç ("trojan horse" launch artifact)**
Tam extension kurmadan denenebilecek küçük standalone web aracı (CSV mail-merge previewer/validator: CSV + {{tag}} şablonu yapıştır, render önizle, eksik-kolon hatalarını yakala). Launch topluluklarına *bunu* gönder, extension'ı sadece footer CTA olarak an. 10 saniyede denenir, "bu şirket kim" güven bariyerini kaldırır.
`Efor: M · Maliyet: $0 · Sinyal: aynı hafta`
İlk adım: Previewer'ı statik sayfa olarak inşa et, önce bir subreddit'te soft-launch, sonra Show HN/PH submission'ı olarak kullan. Her önizleme sonucunda görünür düşük-friction CTA + click-through izle.

### Alternatifler (90+ gün)

- **[İç-döngü] Opt-in "Sent with OutMass" footer + referral kota bonusu** — Kullanıcı-toggle'lı (varsayılan KAPALI) footer, ?ref=<user_id> linki; kayıt getirirse referrer'a bonus kota. Click-tracking altyapısı zaten var. `S · $0 · 1–2 hafta.` *⚖️ Jüri anlaşmazlığı: compounding "listedeki tek gerçek viral döngü" (7, üst-sıra) dedi; icp-fit tuzak saydı (promosyon footer'ı ICP'nin kendi deliverability'sini/EOP skorunu riske atar). Karar: default-OFF, kampanya-başı opt-in, önce 5 ödeyen kullanıcıda deliverability test et, açık kurucu onayı — email-içerik değişikliği politika gereği onay ister.*
- **Kota-duvarı referral nudge** — Free kullanıcı 250/ay limite kampanya ortasında çarpınca upgrade prompt'unun yanında "bir meslektaşını davet et, anında +100" seçeneği. `S · $0 · 2–3 hafta.` *Plan-limit mekaniği user-visible → kurucu onayı + abuse koruması (domain/hesap başına cap) gerekir.*
- **Aynı-şirket-domain sinyali → takım-değerlendirme nudge** — OAuth'tan gelen work-domain'i mevcut kullanıcılarınkiyle eşle; eşleşmede yumuşak "senin gibi takımlar..." banner'ı. `S · $0 · aynı-gün retroaktif kontrol.` İlk adım: Bugün mevcut kayıtlar arası tek SQL sorgusuyla çakışma var mı bak, UI'dan önce. *Meslektaşı isimlendirmeden generic dil kullan (gizlilik/optik).*
- **MSP/IT-danışman affiliate kanalı** — M365 MSP'leri her tenant'a dokunur; bir ilişki düzinelerce koltuğa yayılır. `M · $0 baz (sadece komisyon) · 3–4 hafta.` İlk adım: 25% rev-share yerine ücretsiz client pilotuyla aç. *⚖️ Jüri anlaşmazlığı: icp-fit üst-sıraya koydu (ilişki başına en yüksek ICP kaldıracı); founder-reality tuzak dedi (yavaş satış döngüsü + 5-müşteri güven açığı). Karar: temel ve sosyal-ispat oturunca dene.*
- **Outreach VA / butik ajans referral programı** — VA'lar tekrar-uygulayıcı, her convert roster'a çarpar; per-VA Stripe kupon ile takip. `M · $0 baz · 2–3 hafta.` *⚖️ icp-fit 8 (üst), founder-reality tuzak (çoğu VA client'ının Gmail default'unu kullanır). Karar: sadece client'ları zaten Outlook/M365'te olan VA'ları hedefle.*
- **G2/Capterra "GMass Alternatives" sponsor yerleşimi** — Comparison-sayfa ziyaretçileri şu an ödeyen-araç seçiyor; flat-fee bütçe tavanına uyar. `M · $0–100/ay · 3–4 hafta.` İlk adım: Önce ücretsiz listelemeyi doldur, referral trafiği görünce boost öde. *⚖️ icp-fit 7, compounding tuzak (bu dizinler Outlook araçlarını iyi indekslemeyebilir; yorum enerjisi CWS/Edge yorum tabanına daha iyi harcanır).*
- **Retargeting borusunu şimdi (ücretsiz) döşe, sonra harca** — Bing UET + Google remarketing tag'ini bu hafta ekle (dakikalar); harcamayı ~100–300 aylık ziyaretçi olana kadar açma. `S · $0 şimdi, $20–30/ay sonra · kurulum anında.` İlk adım: Tag'leri ekle, audience boyutunu aylık takvim-kontrolüyle izle (solo kurucu unutmasın).
- **Comparison yazılarını yan-yana video'ya çevir** — Mevcut GMass/YAMM/Mailmeteor yazılarını Outlook-vs-Gmail ekran-paylaşımı videosuna çevir, yazıya göm (dwell-time/SEO). `M · $0 · 2–3 hafta.` *Adil ol, savaşçı değil yardımcı okunsun.*
- **Co-marketing guest-post takası (M365-komşu araçlar)** — Email-finder/enrichment/list-building araçlarıyla karşılıklı yazı + backlink. `M · $0 · 3–5 hafta.` *Not: çoğu komşu araç Gmail-merkezli — Outlook-komşu havuz beklenenden küçük olabilir.*
- **Dikey podcast pitch'leri ("Outlook = cold email'in görmezden gelinen yarısı")** — GMass/Mailmeteor konuğu ağırlamış 10–15 podcast'e contrarian açı. `M · $0 · yavaş, 1–2 ay.` *Arka-plan thread'i olarak tut, ana bahis değil.*
- **"Solo kurucu + AI destek" hikayesini üründen bağımsız pitch et** — HARO/Qwoted/Featured'da somut örnek (sabah bildirilen bug, akşam sevk edildi). `S · $0 · haftalar.` *Sadece iddia baskı altında dayanacaksa pitch et.*
- **Self-hosted "founding member" lifetime deal (AppSumo yerine)** — 20–30 lifetime Pro, sabit fiyat, plain Stripe link, sadece blog/newsletter'dan duyur. AppSumo'nun deal-collector kitlesi kıt destek kapasitesini yer. `S · ~%3 Stripe · günler.` *Cap düşük, özellikler açık tut — lifetime = solo kurucuya sonsuz yük.*
- **LinkedIn Ads — bilinçli ertele, tetikli** — $6–12 CPC'de $200 = ~20–30 tık, anlamsız. Şimdi harcama; sadece agency/recruiting segmentinin organik olarak daha iyi dönüştüğü kanıtlanınca dar $50 InMail testi yap. `$0 şimdi.` İlk adım: Kayıtları inferred hesap-tipine göre etiketle (bu, gelecekteki testi haklı çıkaracak kanıt). Bu bir *dormant not*, bu çeyreğin iş kalemi değil.

---

## Tuzaklar (şimdilik uzak dur)

Jürilerin işaretlediği, kurucunun kısıtlarına yapısal uymayan hamleler:

- **VA/recruiter FB grupları + RevOps Slack'te yavaş güven inşası** — Efor L, 3–6 hafta, geriye kalıcı varlık bırakmaz; en kıt kaynağı (zaman) hafızalı topluluklarda ilgili thread hiç çıkmayabilecekken tüketir.
- **Tek-kanca native Shorts (YT/TikTok/Reels)** — Tüketici-eğlence algoritmaları; B2B Outlook-admin alıcısı bu kitlede yok. Yüksek-hacim, düşük-niyet, dönüşmeyen trafik.
- **Viral X söylemine 15-sn GIF ile atlama** — Thread'in ilk saatlerinde yakalamak için sürekli gerçek-zamanlı izleme; kalıcı varlık yok, saf reaktif zaman yakımı.
- **"Aynı gün sevk ettim" build-in-public mikro-vlog** — Öngörülemez bug zamanlamasına bağlı, ürünü tekrar tekrar "buglu" çerçeveler; kırılgan güven getirisi olan üretim treadmill'i.
- **Indie Hackers milestone post'ları** — Kitle diğer kurucular, M365 alıcısı değil; alkış + geri-bildirim üretir ama gelir üretmez, üstelik sürekli posting kadansı ister.
- **Non-converter'lara kişisel Loom video'ları** — Mevcut avuç dolusu kullanıcının ötesine ölçeklenmez, compound etmez; kıt kaynağa doğrudan vergi. (Aynı çekim eforu mağaza demo videosuna gitsin — her ziyaretçiye çarpar.)
- **Micro-influencer anlaşmaları (Outlook/M365 YouTuber'ları)** — Üç jüri de eleştirdi: "Outlook tips" kitlesi genel-verimlilik/IT'ye eğilimli, bulk/cold gönderen değil; gerçek bütçe + koordinasyon başka kanalda yaşayan (non-owned) videoya gider, dönüşüm zayıf.
- **Cold-email "spam score" paylaşılabilir kart** — Kanıtlanmamış ego-paylaşım içgüdüsüne bahis (insanlar KÖTÜ skoru nadiren paylaşır); zayıf ürün-bağı, olası aylık render maliyeti — send-limit hesaplayıcı gibi gerçek bir sorguyu cevaplamaz.
- **Public template galerisi (self-serve publish flow)** — Basit indirilebilir galeriyle örtüşür ama çok daha ağır (Pro publish UI + boş-galeri cold-start + şablonunu rekabet avantajı gören recruiter'ların paylaşmaması). Kurucu-tohumlu statik galeri bu sorunu zaten atlar.
- **Edge'de sıralı long-tail başlık A/B "thrash"i** — Sık başlık değişimi birikmiş keyword-relevance'ı sıfırlar, dönen aramacıyı şaşırtır; doğru hamle en iyi başlığı BİR kez seçip relevance biriktirmek. (Gerçek ikinci duplicate listeleme = mağaza suspend riski, kesinlikle kaçın.)

---

## Sıralama mantığı (ne neyi açar)

Compounding jürisinin bağımlılık zinciri — sırayı buna göre kur:

1. **Kanonik gerçekler sayfası ÖNCE gelir.** Tüm comparison yazıları, mağaza listeleri ve forum cevapları buraya link verir; otorite tek URL'de toplanır. Onu inşa etmeden diğer SEO parçaları dağınık kalır.
2. **IndexNow/Bing borusunu bir kez döşe.** Sonraki her sayfanın time-to-index'ini günlere indirir — her içerik varlığının değerini hızlandıran altyapı. Deploy'a bir kez bağla, sonsuza dek sıfır-marjinal efor.
3. **Mağaza demo video + başlık revizyonu, HERHANGİ ücretli/launch trafiğinden ÖNCE prerequisite'tir.** Her kanal bu listelemeye ziyaretçi gönderir; video conversion'ı yukarıdaki her şeyi çarparak yükseltir. Paralel iş değil, ön-koşul.
4. **Yakalama sayfası = merkez düğüm.** Comparison yazılarının iç-link hedefi + rakip-fetih reklamlarının varış noktası + forum cevaplarının link hedefi. Üçünü birden besler.
5. **Manuel yorum isteği, herhangi in-product nudge'dan önce yorum tabanını tohumlar** ve istekliliği doğrular.
6. **Tek-atışlık spike'lar (Show HN, Product Hunt, lifetime deal) EN SON** — ancak SEO varlıkları + yorumlar + organik trafik, spike'ın gönderdiği trafiği yakalayıp tutacak hale gelince. Boş kovaya su dökme.

---

## Haftalık ritim önerisi (solo kurucu + AI kaldıraç)

Gerçekçi hedef: **haftada ~4–6 saat pazarlama**, bloklanmış, geri kalan zaman ürün/destek. AI taslak hızı bu ritmi mümkün kılar.

- **Pazartesi — 45 dk · Ölçüm + istihbarat.** Aşağıdaki 3–5 sayıyı logla. Copilot/ChatGPT/Perplexity'ye hedef promptları sor, atıf var mı kaydet. Bing rank kontrolü.
- **İçerik bloğu — ~2 saat · Bir varlık sevk et.** AI ile tek sayfa/tutorial/şablon taslakla, kurucu gözden geçirmesi yap (özellikle şablon faydası + canlı-özellik doğruluğu), yayınla, IndexNow ping otomatik atsın.
- **Dağıtım bloğu — ~1 saat · 2–3 forum/Reddit thread'ine açıklamalı, gerçekten yardımcı cevap** (UTM-linkli). Haftanın en yüksek-niyetli thread'lerini seç.
- **Async — dağınık ~30–60 dk · Yanıtları temizle.** Newsletter/partner/listicle yanıtları, saved-search bildirimleri, gelen destek e-postalarındaki dönüşüm ipuçları.
- **Ayda bir — 30 dk · Retargeting audience boyutu + mağaza listeleme çeviri-drift'i + ücretli deney read'i** (takvim hatırlatıcısı — solo kurucu unutmasın).

İlke: her hafta **bir kalıcı varlık** bırak (sayfa, video, şablon, forum cevabı). Treadmill kanallarına (günlük Shorts, gerçek-zamanlı X izleme) girme — onlar zaman yakar, varlık bırakmaz.

---

## Ölçüm (haftalık izlenecek 3–5 sayı)

1. **Mağaza browse→install conversion** (CWS + Edge, ayrı) — mevcut darboğaz; demo video/başlık işe yarıyor mu.
2. **Yeni kayıt + free→paid dönüşüm** — ve inferred domain-tipine göre ICP karışımı (agency/recruiting oranı LinkedIn/MSP tetiklerini haklı çıkarır).
3. **Bing rank (hedef keyword'ler) VE Copilot/AI-atıf var/yok** — iki AYRI metrik; sıralama kazanımı atıf kazanımıyla karıştırılmasın.
4. **UTM referral tıkları** kaynağa göre (forum / capture sayfası / newsletter / directory) — hangi dağıtım kanalı gerçekten trafik getiriyor.
5. **Haftalık aktif gönderen / gönderilen kampanya** (ürün nabzı) — pazarlamanın getirdiği kullanıcı gerçekten değer alıyor ve tutunuyor mu.

> Küçük N uyarısı: düzinelerce kurulumda haftalık conversion sayıları gürültülü. Çoğu deney için 2–4 hafta pencere kullan, günlük dalgalanmayla karar verme.