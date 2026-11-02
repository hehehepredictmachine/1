// Logo PepeMarketWizard: the existing Pepe-wizard artwork of the panel (src/assets/pepe-wizard.webp) in a rune medallion.
import pepe from "../../assets/pepe-wizard.webp";

export default function WizardLogo({ size = 46 }: { size?: number }) {
  return (
    <span className="wz-logo-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 64 64" className="wz-logo-ring">
        <defs>
          <linearGradient id="wzLogoRing" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3fe6ff" /><stop offset="0.5" stopColor="#b46bff" /><stop offset="1" stopColor="#2fe6a0" />
          </linearGradient>
        </defs>
        <circle cx="32" cy="32" r="29" fill="rgba(8,6,24,0.85)" stroke="url(#wzLogoRing)" strokeWidth="2" />
        <circle cx="32" cy="32" r="31" fill="none" stroke="url(#wzLogoRing)" strokeWidth="0.7" strokeDasharray="2 3" opacity="0.8" />
      </svg>
      <img src={pepe} alt="" className="wz-logo-face" draggable={false} />
    </span>);
}
