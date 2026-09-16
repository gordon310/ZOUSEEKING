# SES 生产权限申请 · 案件回复文案(2026-09-16)

> 案件:`178931383400481`(Support Center,状态 Pending customer action)→ 直接回复此案,粘贴下方正文。
> AWS 要求:说明发送频率、名单维护方式、退信/投诉/退订处理,并给出邮件样例;且授权前须有已验证身份。

---

**Reply (paste into the Support Center case)**

Thank you for your response. Please find the requested details below.

**Account & identities**
- AWS account: 070780358946, Region: Asia Pacific (Singapore) ap-southeast-1
- Verified domain identity: `mail.zoubeacon.com` (Easy DKIM status: SUCCESS)
- Custom MAIL FROM domain: `bounce.mail.zoubeacon.com` (MX and SPF records published, status SUCCESS)
- DMARC record published for `mail.zoubeacon.com` (p=none initially, monitoring aggregate reports)
- A verified email address identity (`gordon310103@gmail.com`) is in place for our own testing
- Sending is done through SMTP (Amazon SES SMTP endpoint, port 587, STARTTLS) with sender `no-reply@mail.zoubeacon.com`; the default configuration set `zoubeacon-tracking` is assigned to the identity

**1. What we send, and how often**
We operate https://zoubeacon.app, a SaaS product for real-estate professionals and consumers in Japan (operator: カナン株式会社 / Canaan K.K., Japan corporate number 6120001261672). We send only **transactional / account-related messages that the recipient's own action triggers**:
1. Email address confirmation sent immediately after a user registers;
2. Password reset email sent when a user requests it;
3. Security notifications when a user changes their password or email address;
4. Occasional service notification when a dataset/report a user explicitly requested has finished generating.

We send **no marketing, no newsletters, no promotional or bulk mail**, and we do not resell sending services.

Expected volume: under 100 messages/day today; we anticipate under 500 messages/day over the next three months, growing gradually with user registrations. Our current maximum sending rate of 1 message/second is more than sufficient.

**2. How we build and maintain our recipient list**
- Recipients are **only** people who registered themselves on our website. Every address is collected through our own signup form and confirmed via the confirmation email above (double opt-in); we never send to unconfirmed addresses.
- Business (organization) accounts may also invite their own colleagues; those invitees must accept the invitation from our email and set their own password before any further mail is sent to them.
- We **never** use purchased, rented, harvested or co-registered lists, and we do not do list scraping or append. There is no third-party list import in our product.
- We do not send to role addresses (info@, sales@, etc.) and we do not send to any address that has hard-bounced, complained or unsubscribed.
- Our application enforces its own per-account quotas and rate limits on user-initiated actions, and the authentication backend limits how many emails can be sent per hour.

**3. How we handle bounces, complaints and opt-outs**
- SES account-level suppression list is enabled for both BOUNCE and COMPLAINT, so SES automatically suppresses those addresses.
- Our identity uses the configuration set `zoubeacon-tracking`, which publishes BOUNCE and COMPLAINT events to the SNS topic `ses-bounces`; we monitor these events. Hard bounces are not retried and the address is suppressed; complaint recipients are removed immediately.
- We target a bounce rate below 2% and a complaint rate below 0.1% (well inside your 0.5% requirement), and we will pause sending and investigate if we approach them.
- Unsubscribe/opt-out: the confirmation, password-reset and security notifications are strictly required for account security, so they cannot be individually unsubscribed (they are only triggered by the user's own action). Any optional notification can be disabled in the user's account settings, and users can request full deletion of their account and personal data at any time (we honour such requests within 24 hours - our privacy policy is at https://zoubeacon.app/privacy.html).

**4. Example of the email we send (registration confirmation)**
From: 小象避坑 ZOUBEACON <no-reply@mail.zoubeacon.com>
Subject: 【小象避坑】请确认你的邮箱 / メールアドレスの確認

Body (HTML, plain branding, no attachments, no tracking pixels, one button; bilingual Chinese/Japanese because our users are Japanese real-estate professionals and Chinese-speaking clients):

  Confirm your email address
  Thanks for registering with 小象避坑 (ZOUBEACON). Click the button below to confirm your email address and start using the service.
  [ 确认邮箱 / メールアドレスを確認する ]  -> https://<our-domain>/auth/confirm?token=...
  If the button does not work, copy the link above into your browser.
  ---
  メールアドレスの確認
  ご登録ありがとうございます。下記のボタンをクリックしてメールアドレスの確認を完了してください。
  If you did not create this account, you can safely ignore this email.
  小象避坑 ZOUBEACON / カナン株式会社

The password-reset email follows the same pattern with subject 【小象避坑】重设密码 / パスワードの再設定 and a single "set a new password" link that expires shortly. All links point to our own domain (https://zoubeacon.app); we send no attachments and no third-party content, and every message is sent only because the recipient acted on our site.

**5. One additional matter for this case**
We submitted this production access request earlier and a determination was recorded, after which the SES console no longer offers the "Request production access" action and `PutAccountDetails` returns:

  ConflictException: an ongoing account details update under review

We have no way to resubmit from the console or the API. Please treat this reply as our production access request for ap-southeast-1, clear the stale/previous review state on the account so the request can be processed (or let us know the exact reason for the earlier determination so we can correct it), and advise if any further detail is required.

Thank you - we are happy to start with a lower quota and increase gradually, and we can provide any further sample content you need.

Kind regards,
Gordon / カナン株式会社 (Canaan K.K.)
https://zoubeacon.app - support contact: gordon310103@gmail.com
