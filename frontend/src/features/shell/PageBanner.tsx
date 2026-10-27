// Page banner of the new panels (approved mockups): breadcrumb, title, one-line purpose, status badges, actions, "Wygląd" and Pepe.
import type { ReactNode } from "react";
import pepe from "../../assets/pepe-wizard.webp";
import { useLook } from "./look";

export default function PageBanner({ kicker, title, subtitle, badges, actions, testId }: {
  kicker: string; title: string; subtitle: string; badges?: ReactNode; actions?: ReactNode; testId?: string;
}) {
  const { openLook } = useLook();
  return (
    <section className="t-banner" aria-labelledby={`${testId ?? "t"}-title`} data-testid={testId}>
      <div className="t-banner-text">
        <p className="t-kicker">{kicker}</p>
        <h1 id={`${testId ?? "t"}-title`}>{title}</h1>
        <p className="t-banner-sub">{subtitle}</p>
        <div className="t-banner-row">
          {badges}
          {actions}
          <button className="t-btn t-btn-acc" onClick={openLook} data-testid="t-look-open" aria-haspopup="dialog">⚙ Wygląd</button>
        </div>
      </div>
      <img className="t-banner-pepe" src={pepe} alt="" aria-hidden="true" width={120} height={126} />
    </section>);
}
