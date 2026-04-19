# ProductHunt Launch Kit — OutMass

Everything you need for a polished Product Hunt launch. Copy-paste ready.

---

## 1. Pick your launch date

**Best days:** Tuesday or Thursday (highest traffic, more reviewers online).
**Avoid:** Monday (competition from weekend backlog), Friday (weekend drop-off), holidays (US traffic dies).

**Timing:** Submissions go live at **00:01 PST** (08:01 UTC, 11:01 Istanbul). The first 4 hours and last 4 hours of the 24h window are the most critical for leaderboard position.

**Recommended:** Launch on a **Thursday**, 2-3 weeks after Chrome Web Store is public. Why:
- Gives time for a handful of real user reviews to show on Chrome Store (trust signal)
- Enhanced Safe Browsing warning starts fading after ~1 week of installs
- Enough runway to build a "notify me on launch" list

---

## 2. Fields to fill in on Product Hunt

### Name
```
OutMass
```

### Tagline (60 chars max, 40-50 ideal)

Three A/B options — pick the one that feels most you:

**Option A (direct, benefit):**
```
Mail merge, A/B, AI writer — inside Outlook
```

**Option B (positioning):**
```
GMass for Outlook — in 10 languages
```

**Option C (founder voice):**
```
Turn Outlook Web into a cold-outreach machine
```

> **Recommendation:** **A** — specific, names three features, says where it lives. "GMass for Outlook" (B) is tempting because of keyword lift, but PH readers may not know what GMass is — weaker for non-GTM audiences.

### Description (260 chars for cards, longer body below)

```
OutMass adds a sidebar to Outlook Web that handles everything cold outreach: CSV mail merge, scheduled sending, A/B subject tests, auto follow-ups, open + click tracking, and a Claude-powered AI writer. Works with Microsoft 365 and Outlook.com. From $9/mo.
```

### Gallery (upload in this order — first is hero)

1. **Hero screenshot** — Campaign tab with merge tags visible (1280×800). The one we built for Chrome Web Store works here.
2. **Reports tab** — Active sub-tab showing campaigns with open/click rates. Social proof "this is a real product people use".
3. **HTML preview modal** — shows a rendered, personalized email.
4. **AI writer modal** — demonstrates the Pro feature.
5. **Settings with Pro features** — skip-repeat-recipients, suppression list, sender profile.

**Optional (big win if you have it):** 30-60s screen recording of a real send flow. CSV upload → type subject → Test Send → view in inbox → Send. Upload as MP4. Video listings get 2-3× engagement on PH.

### Topics (pick 3-4)
- `Email marketing`
- `SaaS`
- `Productivity`
- `Chrome extensions`

### Pricing model
Free + Paid (Freemium). Shows "Free" badge on PH card.

### Makers
Add yourself. If you have a co-founder, add them too — gets them tagged in all threads.

### Hunter
If you know a hunter with 500+ followers on PH, DM them 3-4 days before and ask them to hunt. Otherwise self-hunt — works fine for $9/mo SaaS.

---

## 3. First comment (maker's story) — CRITICAL

This is the single most impactful piece of copy. It shows at the top of the thread, sets tone, and determines whether people read further.

**Template — use this as-is, personalize the middle:**

```
Hey Product Hunt 👋

I'm Ali, a solo maker based in Istanbul. OutMass is the tool I wish existed 
two years ago when I started running cold outreach from Outlook.

The whole market assumes you use Gmail. Every mail-merge tool, every AI 
writer, every analytics dashboard — Gmail-first. If you're on Microsoft 
365 or Outlook.com, your options were:

  1. Switch your entire email to Gmail (not happening when you have 5 
     years of threads and your whole company on M365)
  2. Pay $30+/month for GMass and manage a second inbox
  3. Fake it with Word mail merge and copy-paste (what I did for 6 months)

So I built OutMass. It's a Chrome extension that adds a sidebar to 
Outlook Web with everything a cold-email tool should have:

  • Mail merge from CSV with {{firstName}} / {{company}} / any column
  • Subject A/B testing (Pro)
  • Open + click tracking, unsubscribe handling
  • Scheduled sending across time zones
  • Auto follow-ups for non-openers
  • AI email writer powered by Claude (Pro)
  • 10 UI languages including Arabic RTL

Under the hood, it sends through your own Microsoft Graph API (OAuth 2.0) 
— we never store email contents, we don't proxy through our servers, 
your Outlook account stays entirely yours. No deliverability surprises.

Pricing is deliberately undercut: $9/mo Starter (2k emails), $19/mo Pro 
(10k emails + AI + A/B). Free forever at 50/month.

I'd love your feedback — especially from anyone who's tried mail-merging 
in Outlook and given up. What features would unlock this for your team?

Thank you for checking it out 🙏
— Ali
```

**Personalization points:**
- Change "Istanbul" if you want to highlight something else
- Change "two years ago" to match your real story
- Change the three options numbered list if your workflow was different

**Length rule:** This comment should be 1500-2000 chars. Yours is 1850. Good.

---

## 4. Subheadlines / reply snippets (prepare 6-8)

Questions you WILL get. Pre-drafted replies save you time on launch day.

### Q1: "How is this different from GMass?"
```
GMass is Gmail-only. OutMass is the equivalent for the Outlook ecosystem — 
outlook.live.com, outlook.office.com, outlook.office365.com, personal 
and enterprise. Under the hood we use Microsoft Graph API; GMass uses 
Gmail API. If your team is on M365, OutMass; if you're on Workspace, 
GMass. Both legit, different stacks.
```

### Q2: "Is the AI writer good?"
```
It's Claude (Sonnet for quality). You give it a target persona + 
campaign goal, it drafts subject + body with merge tags pre-filled. 
50 generations/month on Pro. Honest take: I use it as a starting 
point about 60% of the time, still manually edit before sending. 
Great for breaking writer's block, not for one-shot sends.
```

### Q3: "Outlook rate limits must be rough — is this even viable?"
```
Microsoft's limits:
  • Outlook.com personal: ~300/day
  • Microsoft 365 Business: ~10,000/day
  • Exchange enterprise: higher, depends on tenant

OutMass's plan quotas are designed to fit under these comfortably. We 
throttle sends (configurable delay) so you don't trigger anti-spam 
flags. For anyone hitting enterprise limits, talk to me directly.
```

### Q4: "What happens to my data?"
```
Short answer: we store campaign content (because we need to actually 
send it) and recipient lists (same reason). We don't read your inbox 
or touch any incoming mail. We don't use campaign content for AI 
training. Full policy: https://getoutmass.com/privacy.html. GDPR + 
UK GDPR compliant, UK Ltd as data controller.
```

### Q5: "When is Gmail support coming?"
```
Not on the roadmap. Gmail has great tools already — GMass, YAMM, 
Mailmeteor, Mailshake. The problem we solve is Outlook, and we plan 
to go deep on Outlook features (shared mailboxes, Exchange ECC 
integration, Teams hooks) rather than spread thin.
```

### Q6: "Launch deal?"
```
🎁 For Product Hunt — first month of Pro is 50% off. Code LAUNCH50 
at checkout. Expires Sunday midnight PST.
```
> **Set this up in Stripe first!** Create a promotion code `LAUNCH50` in Stripe → Products → Promotions → 50% off first month → set expiry.

### Q7: "Does it work with shared mailboxes / send-as addresses?"
```
Currently: sends from your primary authenticated account only. Shared 
mailbox support is the #1 enterprise request — roadmap for v0.2, 
probably 4-6 weeks. If you want to be a beta tester, drop your email 
in the comments or DM me.
```

### Q8: "Why Outlook specifically?"
```
Because ~400M M365 users + another ~400M personal Outlook.com users 
and nothing built natively for them. Everyone assumes Gmail. That's 
the whole thesis: Gmail has 15 tools, Outlook has 0 good ones. We 
want to be the 1 good one.
```

---

## 5. Launch day schedule (24-hour playbook)

All times in **Istanbul (UTC+3)**. PH day starts at 11:01 Istanbul.

### T-24h (day before launch, evening)
- [ ] Final sanity check: Chrome Web Store listing loads, install works, OAuth works, Stripe live works
- [ ] LAUNCH50 promo code created in Stripe
- [ ] PH listing saved as draft, all fields filled, gallery uploaded
- [ ] First comment written and tested in preview
- [ ] Telegram notification for daily report at 14:00 UTC — confirm it's working
- [ ] Sleep early, you'll be on PH for 24 hours straight

### T-0 to T+4h (the critical window — 11:01 to 15:00 Istanbul)
- [ ] **11:01** — PH goes live, post the first comment immediately
- [ ] **11:05** — Tweet: "Launching OutMass on Product Hunt today! [link]. 10 languages, mail merge for Outlook. Would love your support 🙏"
- [ ] **11:10** — LinkedIn post with the same message + 2-3 screenshots
- [ ] **11:15** — Post in relevant Discord/Slack communities (Indie Hackers, Turkish Founders, Startup School, etc.)
- [ ] **11:30–15:00** — Check PH every 10 minutes. Reply to every comment within 15 minutes. Upvote replies to your comments.
- [ ] Track votes: aim for 100 by T+4h = top-10 potential

### T+4h to T+12h (Istanbul afternoon to evening — 15:00 to 23:00)
- [ ] Keep replying to every comment
- [ ] DM 10-20 people you know personally with the PH link (individually, not a group text) — "Launched today, would love your vote + honest feedback"
- [ ] Post on Reddit (r/Outlook, r/productivity, r/SaaS) — follow each subreddit's self-promotion rules
- [ ] Hacker News Show HN post if you have karma, or politely ask a friend with 500+ karma

### T+12h to T+24h (overnight Istanbul, US peak time — 23:00 to next 11:01)
- [ ] Sleep 6 hours (23:00–05:00 Istanbul) — US reviewers handle their own day
- [ ] Wake at 05:00, catch up on comments — US userbase is active
- [ ] Final push: "Last X hours on PH, thank you to everyone who's helped!" social post
- [ ] **11:00** — Day closes. Screenshot your final rank. Post a thank-you on all channels.

### T+24h+ (launch week)
- [ ] Reply to remaining PH comments over the next 48h
- [ ] Turn every PH install into a manual "thanks for trying" email
- [ ] Write a "What I learned launching on Product Hunt" post — gets additional mileage

---

## 6. Pre-launch funnel — 7 days out

**"Notify me" list** — if you have 100 people signed up waiting, launch momentum is easier.

1. Create a Tally / Typeform: `getoutmass.com/launch` → "Get notified when we launch on Product Hunt + 50% off Pro first month"
2. Post on Twitter, LinkedIn, your personal network every 2 days for the week before
3. Day of launch: email all signups with the PH link + promo code

Pre-launch teaser copy:
```
Spent 18 months building a cold-email tool for Outlook users. 
Sick of Gmail-only options. Going live on Product Hunt next 
Thursday. Get notified + 50% off first month of Pro → [link]
```

---

## 7. Assets checklist

Already in the repo:
- [x] 5 screenshots 1280×800 (can be reused — Chrome Store + PH share)
- [x] Small promo tile 440×280 (might be used for PH card thumbnail if you resize to 240×240)
- [x] Large promo tile 920×680 (good for PH gallery)
- [x] Extension icons

Still to create (optional but high impact):
- [ ] **30-60s product demo video** — simple screen recording, no voice needed, music optional. Loom or QuickTime both fine. Shows: open sidebar → upload CSV → write subject → merge preview → Test Send → receive email → Send real campaign → see Reports.
- [ ] **Launch announcement image** (1200×630 for Twitter/LinkedIn/OG) — "OutMass is live on Product Hunt" + logo + tagline
- [ ] **PH card thumbnail** (240×240 recommended) — square, high contrast, recognizable at tiny size. The "OM" gradient logo works well here.

---

## 8. Metrics to track on launch day

Open in separate tabs at 11:01:
1. **PH listing** — refresh every 5 min for votes, comments
2. **Google Analytics / PostHog** — landing page hits
3. **Chrome Web Store developer dashboard** — install count (updates hourly)
4. **Stripe dashboard** — checkouts started, subscriptions created
5. **PostHog errors** — catch real-world bugs fast

Target by end of day (honest benchmarks for a solo SaaS launch):
- 100-300 PH votes → top 10 of the day
- 20-50 Chrome Web Store installs
- 2-5 paid subscriptions
- 1-2 "this is exactly what I needed" DMs / emails (these are gold)

Don't benchmark against #1 of the day — those are usually 1k+ votes from established startups with dedicated launch teams. Top 10 for a solo maker is a huge win.

---

## 9. After launch

Within 48 hours, write a follow-up:
- Blog post: "What I learned launching OutMass on Product Hunt"
- Update the PH comment with final stats + what's next
- Email paid subscribers with a personal thank-you
- Tweet the final numbers (builds in-public credibility)

Ship improvements based on feedback every week for the first 4 weeks — PH traffic dies, but the 50 users who signed up in week 1 are your product compass.

---

## 10. Things NOT to do

- ❌ Don't buy votes / fake reviews (PH bans for this, ruins reputation permanently)
- ❌ Don't spam-DM hunters asking for hunts ("Hi bro please hunt my product" — universally despised)
- ❌ Don't go dark after launch — staying engaged for a week after is what converts visitors to customers
- ❌ Don't over-respond to negative comments — "thanks for the feedback, here's what we'll do" once is enough
- ❌ Don't forget to actually eat and sleep — 24h of constant monitoring is exhausting
