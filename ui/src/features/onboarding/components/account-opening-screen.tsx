"use client";

import { useEffect, useState } from "react";
import { Check, Sparkles } from "lucide-react";

import { LogoMark } from "@/components/logo-mark";

import styles from "./account-opening-screen.module.css";

const PREVIEWS = [
  "Start with a ready-made assistant, or build an agent your way.",
  "Choose a template, runtime and model that fit your work.",
  "Start chatting on the web. Connect more channels when you're ready.",
];

export function AccountOpeningScreen({ opening = false }: { opening?: boolean }) {
  const [preview, setPreview] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setPreview((index) => (index + 1) % PREVIEWS.length), 6000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className={styles.screen}>
      <div className={styles.content}>
        <div className={styles.brand}><LogoMark size={24} /> Agent Barn</div>
        <div className={styles.illustration} aria-hidden="true">
          <div className={styles.orbit} />
          <div className={styles.orbitInner} />
          <div className={styles.mark}><LogoMark size={64} /></div>
          <span className={styles.spark}><Sparkles size={20} /></span>
          <span className={styles.dot} />
        </div>
        <div role="status" aria-live="polite" aria-atomic="true">
          <h1>{opening ? "Preparing your account" : "Welcome to Agent Barn"}</h1>
          <p className={styles.description}>
            {opening
              ? "We're getting your organization ready for the next step."
              : "We're loading your account and checking where you left off."}
          </p>
        </div>
        <div className={styles.activity} aria-hidden="true"><span /><span /><span /></div>
        <div className={styles.next}>
          <span className={styles.kicker}>Make it yours</span>
          <p key={preview} className={styles.preview}>{PREVIEWS[preview]}</p>
        </div>
        <p className={styles.signedIn}><Check size={14} aria-hidden="true" /> Signed in. We&apos;ll take it from here.</p>
      </div>
    </main>
  );
}
