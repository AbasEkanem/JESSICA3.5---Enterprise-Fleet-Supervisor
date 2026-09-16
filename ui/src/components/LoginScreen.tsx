"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { signIn } from "next-auth/react";
import styles from "./login.module.css";

/** Set to "/jessica-mark.png" to render a raster logo (mix-blend-mode: screen
 *  knocks the black plate out against the dark panel) instead of the vector. */
const LOGO_SRC: string | null = null;

/**
 * Node stars for the mesh backdrop, in the trace layer's 1440x900 viewBox.
 * Deliberately a hard-coded table rather than Math.random(): this screen is
 * server-rendered, and a random field would produce different markup on the
 * client, tripping React's hydration check.
 */
const STARS: ReadonlyArray<{
  x: number;
  y: number;
  r: number;
  delay: number;
  dur: number;
}> = [
  { x: 118, y: 104, r: 1.4, delay: 0, dur: 6.4 },
  { x: 268, y: 214, r: 1, delay: 1.1, dur: 5.2 },
  { x: 402, y: 96, r: 1.2, delay: 2.3, dur: 7.1 },
  { x: 214, y: 452, r: 1, delay: 3.6, dur: 5.8 },
  { x: 536, y: 348, r: 1.5, delay: 0.6, dur: 6.8 },
  { x: 688, y: 178, r: 1.1, delay: 2.9, dur: 5.4 },
  { x: 762, y: 486, r: 1.3, delay: 4.2, dur: 7.4 },
  { x: 908, y: 268, r: 1, delay: 1.7, dur: 6.1 },
  { x: 1024, y: 402, r: 1.4, delay: 3.1, dur: 5.6 },
  { x: 1168, y: 156, r: 1.1, delay: 0.9, dur: 6.9 },
  { x: 1298, y: 336, r: 1.2, delay: 4.7, dur: 5.9 },
  { x: 1382, y: 612, r: 1.3, delay: 2.1, dur: 7.2 },
  { x: 316, y: 706, r: 1.1, delay: 5.3, dur: 6.3 },
  { x: 874, y: 764, r: 1.4, delay: 1.4, dur: 5.5 },
  { x: 1046, y: 668, r: 1, delay: 3.9, dur: 6.6 },
  { x: 588, y: 840, r: 1.2, delay: 0.3, dur: 7 },
];


/**
 * Jessica 3.5 sign-in — dark-only neural-mesh panel.
 * Auth wiring (NextAuth, app/api/auth/[...nextauth]/route.ts):
 *   • Google → signIn("google") full-page redirect.
 *   • Email  → TWO-STEP credentials flow: authorize() rejects a sign-in
 *     without firstName, so step 1 collects the email and step 2 the profile
 *     name before signIn("credentials", {..., redirect: false}). On success
 *     the JWT session updates and page.tsx re-renders past this screen.
 */
export function LoginScreen() {
  const [step, setStep] = useState<1 | 2>(1);
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cursor spotlight + panel tilt. Both are rAF-throttled so the mousemove
  // handler never writes layout-affecting styles more than once per frame.
  const pageRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const frameRef = useRef(0);

  useEffect(() => {
    // Coarse pointers (touch) and reduced-motion users get the static scene.
    const fine = window.matchMedia("(pointer: fine)").matches;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine || still) return;

    function onMove(event: PointerEvent) {
      if (frameRef.current) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = 0;
        const page = pageRef.current;
        const panel = panelRef.current;
        if (!page || !panel) return;

        const rect = page.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        // 1. Spotlight: paint the cursor's position into the halo's centre.
        //    These names must match the .spotlight consumer in the stylesheet
        //    (--j-mx / --j-my); px values are fine for the gradient's origin.
        page.style.setProperty("--j-mx", `${x}px`);
        page.style.setProperty("--j-my", `${y}px`);

        // 2. Tilt: a subtle 3D lean, strongest at the panel's edges.
        const panelRect = panel.getBoundingClientRect();
        const dx = (event.clientX - (panelRect.left + panelRect.width / 2)) / panelRect.width;
        const dy = (event.clientY - (panelRect.top + panelRect.height / 2)) / panelRect.height;
        const clamp = (n: number) => Math.max(-1, Math.min(1, n));
        page.style.setProperty("--j-tilt-y", `${clamp(dx) * 4}deg`);
        page.style.setProperty("--j-tilt-x", `${clamp(-dy) * 3.4}deg`);
      });
    }

    function onLeave() {
      const page = pageRef.current;
      if (!page) return;
      page.dataset.spot = "off";
      page.style.setProperty("--j-tilt-x", "0deg");
      page.style.setProperty("--j-tilt-y", "0deg");
    }

    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, []);

  function handleEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setStep(2);
  }


  async function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!firstName.trim()) {
      setError("First name is required.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      const res = await signIn("credentials", {
        email: email.trim(),
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        redirect: false,
      });
      if (res?.error) {
        setError("Sign-in failed. Check the details and try again.");
        setPending(false);
      }
      // On success the session updates and page.tsx re-renders without us.
    } catch {
      setError("We couldn't sign you in. Please try again.");
      setPending(false);
    }
  }

  function handleGoogle() {
    setError(null);
    signIn("google", { callbackUrl: "/" }).catch(() => {
      setError("Google sign-in failed. Try the email option below.");
    });
  }

  return (
    <main className={styles.page} ref={pageRef}>
      {/* Atmosphere stack — all at z-index:-1, painted in DOM order so the
          spotlight reads as light through the mesh and the grain sits on top
          of everything to break up gradient banding. */}
      <div className={styles.aurora} aria-hidden="true" />
      <div className={styles.spotlight} aria-hidden="true" />
      <div className={styles.grain} aria-hidden="true" />

      <NeuralMesh />
      <TraceLines />

      <section className={styles.panel}>
        <div className={styles.markWrap}>
          {/* Radar pings radiating from the mark. Absolutely positioned on
              .markWrap's centre by the stylesheet. */}
          <span className={styles.ping} aria-hidden="true" />
          <span className={styles.ping} aria-hidden="true" />

          {LOGO_SRC ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className={styles.markImage} src={LOGO_SRC} alt="Jessica" />
          ) : (
            <JessicaMark />
          )}
        </div>

        <h1 className={styles.title}>
          Welcome to <span className={styles.titleAccent}>Jessica 3.5</span>
        </h1>
        <p className={styles.subtitle}>Your Enterprise Fleet Supervisor</p>

        {/* Topology nod: Jessica supervises 4 domain supervisors. */}
        <p className={styles.status}>
          <span className={styles.statusDot} aria-hidden="true" />
          Fleet online
          <span className={styles.statusSep} aria-hidden="true">
            ·
          </span>
          4 supervisors
        </p>

        {step === 1 ? (
          <>
            <button type="button" className={styles.google} onClick={handleGoogle}>
              <GoogleMark />
              Continue with Google
            </button>

            <div className={styles.divider}>or</div>

            <form onSubmit={handleEmail} noValidate>
              <label className={styles.field}>
                <span className={styles.srOnly}>Email address</span>
                <input
                  className={styles.email}
                  type="email"
                  name="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </label>

              <button
                type="submit"
                className={styles.submit}
                disabled={email.trim().length === 0}
              >
                Continue with email
              </button>
            </form>
          </>
        ) : (
          <form onSubmit={handleProfileSubmit} noValidate>
            <label className={styles.field}>
              <span className={styles.srOnly}>First name</span>
              <input
                className={styles.email}
                type="text"
                name="firstName"
                autoComplete="given-name"
                placeholder="First name"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                autoFocus
                required
              />
            </label>

            <label className={`${styles.field} ${styles.fieldGap}`}>
              <span className={styles.srOnly}>Last name (optional)</span>
              <input
                className={styles.email}
                type="text"
                name="lastName"
                autoComplete="family-name"
                placeholder="Last name (optional)"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
              />
            </label>

            <button type="submit" className={styles.submit} disabled={pending}>
              {pending ? "Initializing workspace…" : "Enter workspace"}
            </button>

            <button
              type="button"
              className={styles.back}
              onClick={() => {
                setError(null);
                setStep(1);
              }}
            >
              ← Use a different account
            </button>
          </form>
        )}

        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}

        <p className={styles.secure}>
          <ShieldIcon />
          Encrypted end to end. Jessica never stores your password.
        </p>
      </section>
    </main>
  );
}

export default LoginScreen;

/* ---------------------------------------------------------------- graphics */

/** Jessica's brain-network mark, traced to vector so it takes the theme color. */
function JessicaMark() {
  return (
    <svg
      className={`${styles.mark} ${styles.markPulse}`}
      viewBox="0 0 120 106"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Jessica"
    >
      <g
        className={styles.markLinks}
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
      >
        <path
          pathLength={100}
          d="M21.7 18.9 51.1 8M21.7 18.9 8 42.2M21.7 18.9 33.7 39.1M51.1 8 80.5 9.4M51.1 8 62 27.2M51.1 8 33.7 39.1M80.5 9.4 62 27.2M80.5 9.4 104.5 26.8M80.5 9.4 80.5 43.6M62 27.2 80.5 43.6M62 27.2 51.8 48.7M104.5 26.8 80.5 43.6M104.5 26.8 112 55.2M8 42.2 18.3 64.8M33.7 39.1 51.8 48.7M33.7 39.1 18.3 64.8M80.5 43.6 51.8 48.7M80.5 43.6 92.1 72.3M51.8 48.7 61 70.3M51.8 48.7 38.4 74.7M112 55.2 92.1 72.3M18.3 64.8 38.4 74.7M18.3 64.8 61 70.3M38.4 74.7 61 70.3M61 70.3 92.1 72.3M61 70.3 79.2 98M92.1 72.3 79.2 98"
        />
      </g>
      <g
        className={styles.markNodes}
        fill="var(--j-surface)"
        stroke="currentColor"
        strokeWidth="2.8"
      >
        <circle cx="21.7" cy="18.9" r="4.6" />
        <circle cx="51.1" cy="8" r="4.6" />
        <circle cx="80.5" cy="9.4" r="4.6" />
        <circle cx="62" cy="27.2" r="4.6" />
        <circle cx="104.5" cy="26.8" r="4.6" />
        <circle cx="8" cy="42.2" r="4.6" />
        <circle cx="33.7" cy="39.1" r="4.6" />
        <circle cx="80.5" cy="43.6" r="4.6" />
        <circle cx="51.8" cy="48.7" r="4.6" />
        <circle cx="112" cy="55.2" r="4.6" />
        <circle cx="18.3" cy="64.8" r="4.6" />
        <circle cx="38.4" cy="74.7" r="4.6" />
        <circle cx="61" cy="70.3" r="4.6" />
        <circle cx="92.1" cy="72.3" r="4.6" />
        <circle cx="79.2" cy="98" r="4.6" />
      </g>
    </svg>
  );
}

/**
 * Signal traces — data-highway lines with light travelling along them, plus a
 * star field of node dots and expanding "ping" rings. Sits between the mesh and
 * the panel to give the backdrop depth. Fixed 1440x900 viewBox scaled to cover;
 * preserveAspectRatio is intentional since the scene is purely decorative.
 */
function TraceLines() {
  return (
    <svg
      className={styles.traceSvg}
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMidYMid slice"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Faint static rail first, then the two travelling lights. The dash
          pattern in .trace (130 on, 2100 off, offset cycled by exactly one
          full period) keeps a single pulse in flight per wire. */}
      <path
        className={styles.traceRail}
        d="M-80 280C160 140 400 420 700 300 1000 180 1240 420 1520 260"
      />
      <path
        className={styles.trace}
        d="M-80 280C160 140 400 420 700 300 1000 180 1240 420 1520 260"
      />
      <path
        className={styles.trace}
        d="M-80 620C180 700 420 480 720 580 1020 680 1260 470 1520 560"
      />

      <g>
        {STARS.map((s) => (
          <circle
            key={`${s.x}-${s.y}`}
            className={styles.star}
            cx={s.x}
            cy={s.y}
            r={s.r}
            style={{ animationDelay: `${s.delay}s`, animationDuration: `${s.dur}s` }}
          />
        ))}
      </g>
    </svg>
  );
}

function NeuralMesh() {
  return (
    <div className={styles.mesh} aria-hidden="true">
      <svg className={styles.meshSvg} xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="jessica-mesh-a" width="88" height="88" patternUnits="userSpaceOnUse">
            <g stroke="currentColor" strokeWidth="1" fill="none">
              <path d="M0 0 44 44 88 0M0 88 44 44 88 88M0 44H88" />
            </g>
            <g fill="currentColor">
              <circle cx="0" cy="0" r="2.4" />
              <circle cx="88" cy="0" r="2.4" />
              <circle cx="0" cy="88" r="2.4" />
              <circle cx="88" cy="88" r="2.4" />
              <circle cx="44" cy="44" r="3" />
              <circle cx="0" cy="44" r="1.8" />
              <circle cx="88" cy="44" r="1.8" />
            </g>
          </pattern>

          <pattern
            id="jessica-mesh-b"
            width="146"
            height="146"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(21)"
          >
            <g stroke="currentColor" strokeWidth="1" fill="none" opacity="0.6">
              <path d="M0 0 73 73 146 0M0 146 73 73 146 146M73 0V146" />
            </g>
            <g fill="currentColor" opacity="0.6">
              <circle cx="73" cy="73" r="2.6" />
              <circle cx="73" cy="0" r="2" />
              <circle cx="73" cy="146" r="2" />
            </g>
          </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#jessica-mesh-a)" />
        <rect width="100%" height="100%" fill="url(#jessica-mesh-b)" />

        <circle className={styles.pulse} cx="14%" cy="26%" r="4" />
        <circle className={styles.pulse} cx="83%" cy="34%" r="4" />
        <circle className={styles.pulse} cx="24%" cy="78%" r="4" />
        <circle className={styles.pulse} cx="72%" cy="82%" r="4" />
      </svg>
    </div>
  );
}

/* Google "G" — current 4-color mark, unmodified per Google's brand guidelines. */
function GoogleMark() {
  return (
    <svg
      className={styles.googleMark}
      viewBox="0 0 48 48"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18C11.25 26.86 11 25.45 11 24s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24s.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg
      className={styles.secureIcon}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 1.6 13.2 3.6v4.1c0 3.2-2.1 5.6-5.2 6.7-3.1-1.1-5.2-3.5-5.2-6.7V3.6L8 1.6Z" />
      <path d="m5.9 7.9 1.5 1.5 2.8-2.9" />
    </svg>
  );
}

