// KinoDraw for Classroom on classroom.google.com: a "Make a doodle video" button for the teachers of
// the class on screen, a small sign-in chip when KinoDraw isn't signed in yet, and nothing at all
// for anyone else. It lives in a closed shadow root, so Classroom's styles can't reach it, and it never
// calls Google itself: this script runs with Classroom's origin, so the service worker does the asking.
(() => {
  const TAG = 'kinodraw-for-classroom';   // placed on the page by classroom.css
  // A class's pages: /c/<code> (Stream), /w/<code>/t/all (Classwork), /r/<code>/… (People); /u/<n>/ picks the account.
  const CLASS_PAGE = /^\/(?:u\/\d+\/)?[cwr]\/([A-Za-z0-9_=-]+)/;
  const SVG = 'http://www.w3.org/2000/svg';
  const STYLE = `
    button {
      all: unset; box-sizing: border-box; display: inline-flex; align-items: center; gap: 8px;
      height: 44px; padding: 0 18px 0 14px; border: 2px solid #1b1b1b; border-radius: 14px;
      background: #f57c00; color: #1b1b1b; box-shadow: 0 3px 0 #1b1b1b; cursor: pointer;
      font: 600 15px/1 'Google Sans', Roboto, Arial, sans-serif; white-space: nowrap;
    }
    button:hover { background: #ff8f1f; }
    button:active { transform: translateY(2px); box-shadow: 0 1px 0 #1b1b1b; }
    button:focus-visible { outline: 3px solid #1e6fd9; outline-offset: 3px; }
    svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .chip {
      height: 32px; padding: 0 12px 0 10px; gap: 6px; border-width: 1.5px; border-radius: 16px;
      background: #fff; box-shadow: 0 2px 0 #1b1b1b; font-size: 13px; font-weight: 500;
    }
    .chip:hover { background: #fff3e0; }
    .chip svg { width: 16px; height: 16px; color: #e65100; }
  `;

  let host = null;
  let root = null;          // closed: Classroom's scripts can't reach in either
  let code = '';            // the class on screen
  let signingIn = false;    // the teacher went to the studio tab to sign in

  update();
  navigation.addEventListener('currententrychange', () => update());   // Classroom changes pages without reloading
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && signingIn) {         // back from signing in: the chip becomes the button
      signingIn = false;
      update(true);
    }
  });

  async function update(again = false) {
    const next = location.pathname.match(CLASS_PAGE)?.[1] ?? '';
    if (next === code && !again) return;
    code = next;
    show(null);
    if (!next) return;
    const answer = await ask({ type: 'teacher-status', courseCode: next, accountEmail: accountEmail() });
    if (next === code) show(answer);   // unless the teacher has moved on to another class meanwhile
  }

  function show(answer) {
    if (answer?.status !== 'teacher' && answer?.status !== 'signed-out') {
      host?.remove();                  // students, other teachers' classes and errors: nothing on the page
      return;
    }
    if (!root) {
      host = document.createElement(TAG);
      root = host.attachShadow({ mode: 'closed' });
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(STYLE);
      root.adoptedStyleSheets = [sheet];
    }
    root.replaceChildren(answer.status === 'teacher'
      ? button('', 'Make a doodle video', `Make a hand-drawn video and post it to ${answer.course?.name || 'this class'}`, open)
      : button('chip', 'KinoDraw · Sign in', 'Sign in with Google to make doodle videos for this class', () => {
        signingIn = true;
        open();
      }));
    if (!host.isConnected) document.documentElement.append(host);
  }

  function button(kind, label, hint, onClick) {
    const element = document.createElement('button');
    element.type = 'button';
    element.className = kind;
    element.title = hint;
    element.append(pencil(), label);
    element.addEventListener('click', onClick);
    return element;
  }

  async function open() {
    const opened = await ask({ type: 'open-studio', courseCode: code, accountEmail: accountEmail() });
    if (!opened) host?.remove();       // the extension was updated or removed: this button can't work anymore
  }

  async function ask(message) {
    try {
      return await chrome.runtime.sendMessage(message);
    } catch {
      return null;                     // the extension was updated or removed since this page loaded
    }
  }

  // The Google Account button's label includes the signed-in address ("Google Account: Jo Park (jo.park@school.org)");
  // only the address is read, so the page's language doesn't matter. It's just a hint for which account to sign in with.
  function accountEmail() {
    const label = document.querySelector('a[href^="https://accounts.google.com/SignOutOptions"]')?.getAttribute('aria-label');
    return label?.match(/[^\s()]+@[^\s()]+\.[^\s()]+/)?.[0].toLowerCase() ?? '';
  }

  // A pencil drawing a squiggle.
  function pencil() {
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    for (const d of ['M15.2 3.8a2.1 2.1 0 0 1 3 3L8.4 16.6l-4.2 1.2 1.2-4.2z', 'M3 21c2.2-1.6 3.8-1.6 5.4 0s3.4 1.6 5.4 0']) {
      const path = document.createElementNS(SVG, 'path');
      path.setAttribute('d', d);
      svg.append(path);
    }
    return svg;
  }
})();
