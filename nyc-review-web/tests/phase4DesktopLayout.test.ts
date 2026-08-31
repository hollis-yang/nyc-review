import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

function assertInOrder(source: string, tokens: string[]) {
  let cursor = -1;
  for (const token of tokens) {
    const next = source.indexOf(token, cursor + 1);
    assert.notEqual(next, -1, `Missing ordered token: ${token}`);
    assert.ok(next > cursor, `Out-of-order token: ${token}`);
    cursor = next;
  }
}

test('my profile keeps all nine surfaces in a sticky desktop workspace', () => {
  const page = readSource('../src/pages/MyProfile/index.tsx');
  const styles = readSource('../src/pages/MyProfile/MyProfile.module.css');

  for (const section of [
    'notes',
    'favorites',
    'itineraries',
    'vouchers',
    'reminders',
    'memory',
    'followers',
    'following',
    'checkin',
  ]) {
    assert.match(page, new RegExp(`'${section}'`));
  }
  for (const call of [
    'getMe',
    'getUserInfo',
    'getBlogsOfMe',
    'getProfileAssets',
    'getFollowers',
    'getFollowing',
    'getSignCalendar',
    'sign',
  ]) {
    assert.match(page, new RegExp(`${call}\\(`));
  }
  assert.match(page, /styles\.desktopLayout/);
  assert.match(page, /styles\.profileRail/);
  assert.match(page, /data-section=\{activeSection\}/);
  assert.match(page, /<FootBar activeBtn=\{4\}/);
  assertInOrder(page, [
    'styles.profileCard',
    'styles.activityCard',
    'styles.content} data-section',
  ]);
  assert.equal(page.match(/\/imgs\/icons\/default-icon\.png/g)?.length, 1);

  assert.match(styles, /\.desktopLayout,[\s\S]*?\.profileRail\s*\{\s*display:\s*contents;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.desktopLayout\s*\{[^}]*grid-template-columns:\s*340px minmax\(0, 1fr\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.profileRail\s*\{[^}]*position:\s*sticky;[^}]*display:\s*flex;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.profileCard,[\s\S]*?\.activityCard,[\s\S]*?\.content\s*\{[^}]*width:\s*100%;[^}]*box-sizing:\s*border-box;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.content\s*\{[^}]*min-width:\s*0;[^}]*overflow:\s*visible;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.checkInPanel\s*\{[^}]*width:\s*min\(640px, 100%\)/s);
  assert.match(styles, /\.calendarGrid\s*\{[^}]*grid-template-columns:\s*repeat\(7, minmax\(0, 1fr\)\)/s);
});

test('other profile keeps follow and lazy common-follow behavior in a two-column desktop view', () => {
  const page = readSource('../src/pages/OtherProfile/index.tsx');
  const styles = readSource('../src/pages/OtherProfile/OtherProfile.module.css');

  assert.match(page, /follow\(user\.id, !followed\)/);
  assert.match(page, /key === '2' && user/);
  assert.match(page, /getCommonFollows\(user\.id\)/);
  assert.match(page, /navigate\(`\/blog-detail\/\$\{b\.id\}`\)/);
  assert.match(page, /navigate\(`\/user\/\$\{u\.id\}`\)/);
  assert.match(page, /<Tabs\.Tab title=\{t\('otherProfile\.notes'\)\} key="1">/);
  assert.match(page, /<Tabs\.Tab title=\{t\('otherProfile\.commonFollows'\)\} key="2">/);
  assert.match(page, /<FootBar activeBtn=\{0\}/);

  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.scroll\s*\{[^}]*grid-template-columns:\s*320px minmax\(0, 1fr\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.profileCard\s*\{[^}]*position:\s*sticky;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.contentCard\s*\{[^}]*min-width:\s*0;/s);
  assert.match(styles, /@media \(min-width: 768px\) and \(max-width: 1023px\)[\s\S]*?\.scroll\s*\{[^}]*width:\s*min\(760px, 100%\)/s);
});

test('profile edit preserves immediate field updates inside a desktop settings grid', () => {
  const page = readSource('../src/pages/ProfileEdit/index.tsx');
  const styles = readSource('../src/pages/ProfileEdit/ProfileEdit.module.css');

  for (const call of ['uploadBlogImage', 'updateUser', 'updateUserInfo']) {
    assert.match(page, new RegExp(`${call}\\(`));
  }
  for (const key of [
    'profileEdit.avatar',
    'profileEdit.nickname',
    'profileEdit.intro',
    'profileEdit.language',
    'profileEdit.accountSecurity',
    'profileEdit.gender',
    'profileEdit.community',
    'profileEdit.birthday',
  ]) {
    assert.match(page, new RegExp(key.replace('.', '\\.')));
  }
  assert.match(page, /styles\.settingsGrid/);
  assert.equal(page.match(/styles\.settingsColumn/g)?.length, 2);
  assert.match(page, /accept="image\/jpeg,image\/png,image\/webp"/);
  assert.match(page, /maxLength=\{128\}/);
  assert.match(page, /localStorage\.setItem\('appLanguage'/);
  assert.match(page, /value\.filter\(Boolean\)\.join\(' '\)/);
  assert.match(page, /navigate\('\/account-security'\)/);
  assert.match(page, /<FootBar activeBtn=\{4\}/);
  assert.equal(page.match(/<button type="button" className=\{styles\.infoItem\}/g)?.length, 8);
  assertInOrder(page, [
    ">{t('profileEdit.avatar')}</",
    ">{t('profileEdit.nickname')}</",
    ">{t('profileEdit.intro')}</",
    ">{t('profileEdit.language')}</",
    ">{t('profileEdit.accountSecurity')}</",
    ">{t('profileEdit.gender')}</",
    ">{t('profileEdit.community')}</",
    ">{t('profileEdit.birthday')}</",
  ]);

  assert.match(styles, /\.settingsGrid,[\s\S]*?\.settingsColumn\s*\{\s*display:\s*contents;/s);
  assert.match(styles, /@media \(min-width: 768px\) and \(max-width: 1023px\)[\s\S]*?\.scroll\s*\{[^}]*width:\s*min\(760px, 100%\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.settingsGrid\s*\{[^}]*width:\s*min\(960px, 100%\);[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/s);
});

test('account security and forgot password use separate desktop canvases', () => {
  const account = readSource('../src/pages/AccountSecurity/index.tsx');
  const forgot = readSource('../src/pages/ForgotPassword/index.tsx');
  const styles = readSource('../src/pages/AccountSecurity/SecurityForm.module.css');

  assert.match(account, /styles\.securityScroll/);
  assert.match(account, /styles\.securityCards/);
  assert.match(account, /getAccountSecurityStatus\(\)/);
  assert.match(account, /setRecoveryKey\(\{ currentPassword: keyPassword, recoveryKey \}\)/);
  assert.match(account, /changePassword\(\{ currentPassword, newPassword \}\)/);
  assert.match(account, /sessionStorage\.removeItem\('token'\)/);
  assert.match(account, /window\.location\.assign\('\/login\?passwordChanged=1'\)/);
  assert.match(account, /<FootBar activeBtn=\{4\}/);
  assertInOrder(account, [
    "t('accountSecurity.recoveryTitle')",
    "t('accountSecurity.changePasswordTitle')",
  ]);

  assert.match(forgot, /styles\.forgotScroll/);
  assert.match(forgot, /styles\.forgotCard/);
  assert.match(forgot, /resetPassword\(\{/);
  assert.match(forgot, /navigate\('\/login\?passwordReset=1', \{ replace: true \}\)/);
  assert.match(forgot, /<PhoneNumberField/);
  assert.match(forgot, /value=\{recoveryKey\}/);
  assert.match(forgot, /value=\{newPassword\}/);
  assert.match(forgot, /value=\{confirmation\}/);
  assert.match(forgot, /disabled=\{submitting\}/);
  assertInOrder(forgot, [
    'if (!phoneNumber.trim() || !recoveryKey || !newPassword || !confirmation)',
    'if (newPassword !== confirmation)',
    'if (!isStrongRegistrationPassword(newPassword))',
    'if (!isStrongRecoveryKey(recoveryKey))',
    'await resetPassword({',
  ]);
  assert.doesNotMatch(forgot, /securityCards/);

  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.securityCards\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/s);
  assert.match(styles, /@media \(min-width: 768px\) and \(max-width: 1023px\)[\s\S]*?\.securityScroll\s*\{[^}]*width:\s*min\(760px, 100%\)/s);
  assert.match(styles, /\.forgotScroll\s*\{[^}]*width:\s*min\(calc\(var\(--desktop-form-width\) \+ \(var\(--desktop-page-gutter\) \* 2\)\), 100%\)/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.securityCards\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/s);
});

test('login and register share a desktop brand panel without entering primary navigation', () => {
  const login = readSource('../src/pages/Login/index.tsx');
  const register = readSource('../src/pages/Register/index.tsx');
  const styles = readSource('../src/pages/Login/Login.module.css');
  const app = readSource('../src/App.tsx');

  for (const page of [login, register]) {
    assert.match(page, /styles\.authPanel/);
    assert.match(page, /styles\.formColumn/);
    assert.match(page, /styles\.agreement/);
    assert.match(page, /disabled=\{submitting\}/);
    assertInOrder(page, ['styles.brand', 'styles.formCard', 'styles.agreement']);
  }
  assert.match(login, /const redirect = searchParams\.get\('redirect'\) \|\| '\/'/);
  assert.match(login, /const registerUrl = `\/register\?redirect=\$\{encodeURIComponent\(redirect\)\}`/);
  assert.match(login, /loginByPassword\(\{ regionCode, phoneNumber: phoneNumber\.trim\(\), password \}\)/);
  assert.match(login, /<PhoneNumberField/);
  assert.match(login, /type=\{showPassword \? 'text' : 'password'\}/);
  assert.match(login, /setShowPassword\(!showPassword\)/);
  assert.match(login, /<Link to="\/forgot-password">/);
  assert.match(login, /navigate\(redirect, \{ replace: true \}\)/);
  assertInOrder(login, [
    'if (!agreed)',
    'if (!phoneNumber.trim() || !password)',
    'setSubmitting(true)',
    'await loginByPassword',
  ]);
  assert.match(login, /passwordChanged/);
  assert.match(login, /passwordReset/);
  assert.match(register, /const loginUrl = `\/login\?redirect=\$\{encodeURIComponent\(redirect\)\}`/);
  assert.match(register, /isStrongRegistrationPassword\(password\)/);
  assert.match(register, /maxLength=\{32\}/);
  assert.equal(register.match(/type=\{showPassword \? 'text' : 'password'\}/g)?.length, 2);
  assert.match(register, /navigate\(redirect, \{ replace: true \}\)/);
  assertInOrder(register, [
    'if (!agreed)',
    'if (!phoneNumber.trim() || !password || !confirmPassword)',
    'if (password !== confirmPassword)',
    'if (!isStrongRegistrationPassword(password))',
    'await register({',
  ]);

  assert.match(styles, /\.authPanel,[\s\S]*?\.formColumn\s*\{\s*display:\s*contents;/s);
  assert.match(styles, /@media \(min-width: 768px\) and \(max-width: 1023px\)[\s\S]*?\.scroll\s*\{[^}]*width:\s*min\(592px, 100%\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.authPanel\s*\{[^}]*width:\s*min\(1040px, 100%\);[^}]*grid-template-columns:\s*minmax\(300px, 0\.9fr\) minmax\(420px, 1\.1fr\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.authPanel\s*\{[^}]*box-sizing:\s*border-box;/s);
  assert.match(styles, /@media \(min-width: 1024px\) and \(max-height: 720px\)[\s\S]*?\.scroll\s*\{[^}]*justify-content:\s*flex-start;/s);

  const navigationList = app.match(/const routesWithPrimaryNavigation = \[([\s\S]*?)\];/)?.[1] ?? '';
  assert.doesNotMatch(navigationList, /login|register|forgot-password/);
});
