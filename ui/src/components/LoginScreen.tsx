"use client";

import { useState, type FormEvent } from "react";
import { signIn } from "next-auth/react";
import styles from "./login.module.css";

/** Set to "/jessica-mark.png" to render a raster logo (mix-blend-mode: screen
 *  knocks the black plate out against the dark panel) instead of the vector. */
const LOGO_SRC: string | null = null;

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
    <main className={styles.page}>
      <NeuralMesh />

      <section className={styles.panel}>
        <div className={styles.markWrap}>
          {LOGO_SRC ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className={styles.markImage} src={LOGO_SRC} alt="Jessica" />
          ) : (
            <JessicaMark />
          )}
        </div>

        <h1 className={styles.title}>Welcome to Jessica 3.5</h1>
        <p className={styles.subtitle}>Your Enterprise Fleet Supervisor</p>

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
      className={styles.mark}
      viewBox="0 0 120 106"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Jessica"
    >
      <g stroke="currentColor" strokeWidth="2.6" strokeLinecap="round">
        <path d="M21.7 18.9 51.1 8M21.7 18.9 8 42.2M21.7 18.9 33.7 39.1M51.1 8 80.5 9.4M51.1 8 62 27.2M51.1 8 33.7 39.1M80.5 9.4 62 27.2M80.5 9.4 104.5 26.8M80.5 9.4 80.5 43.6M62 27.2 80.5 43.6M62 27.2 51.8 48.7M104.5 26.8 80.5 43.6M104.5 26.8 112 55.2M8 42.2 18.3 64.8M33.7 39.1 51.8 48.7M33.7 39.1 18.3 64.8M80.5 43.6 51.8 48.7M80.5 43.6 92.1 72.3M51.8 48.7 61 70.3M51.8 48.7 38.4 74.7M112 55.2 92.1 72.3M18.3 64.8 38.4 74.7M18.3 64.8 61 70.3M38.4 74.7 61 70.3M61 70.3 92.1 72.3M61 70.3 79.2 98M92.1 72.3 79.2 98" />
      </g>
      <g fill="var(--j-surface)" stroke="currentColor" strokeWidth="2.8">
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

