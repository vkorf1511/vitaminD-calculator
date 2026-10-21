"use client";

import { useEffect, useState } from "react";

export default function SuccessfulSubmission() {
  const [secondsRemaining, setSecondsRemaining] = useState(7);

  useEffect(() => {
    const countdown = window.setInterval(() => {
      setSecondsRemaining((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    const redirect = window.setTimeout(() => {
      window.location.assign("/");
    }, 7000);

    return () => {
      window.clearInterval(countdown);
      window.clearTimeout(redirect);
    };
  }, []);

  return (
    <main className="success-page">
      <section className="success-card" aria-live="polite">
        <span className="success-icon" aria-hidden="true">✓</span>
        <p className="eyebrow">YOU’RE ALL SET</p>
        <h1>Your signup was successful!</h1>
        <p>Your details are saved. We’ll use your location and skin type to personalize your daily Vitamin D window.</p>
        <a className="success-return" href="/">Return to the main app</a>
        <p className="success-countdown">
          Taking you back automatically in <strong>{secondsRemaining}</strong> seconds.
        </p>
      </section>
    </main>
  );
}
