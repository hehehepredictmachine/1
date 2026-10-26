// AI Neural Lab (stage 1: layout only). The 3D views come in stage 3 with the real structures of the models present in the repository
// (docs/PEPE_UI_AUDIT.md §8); nothing here draws or animates a model yet.
import { NotIntegrated } from "../../shell/StateView";

export default function AiNeuralLabPage() {
  return (
    <div className="t-page" data-testid="page-ai-neural-lab">
      <div className="t-page-head">
        <h1>AI Neural Lab</h1>
        <p className="t-dim">Struktury modeli, telemetria, metryki, trening i wdrożenia – wyłącznie dla modeli rzeczywiście obecnych w bocie.</p>
      </div>
      <NotIntegrated title="Neural Network 3D" stage={3} testId="nl-3d"
        sources={["GET /api/v1/lab/neural (warstwy + telemetria NSS)", "artefakt Decision Tree: tree_structure.json", "GET /api/v1/flow-context/markov (Monte Carlo)"]}>
        <p className="t-note">Animacje bez rzeczywistej telemetrii będą oznaczone jako „Illustrative visualization”.</p>
      </NotIntegrated>
      <div className="t-two">
        <NotIntegrated title="Modele i metryki" stage={3} testId="nl-models"
          sources={["GET /api/v1/training/models?instrument=", "GET /api/v1/ml/status", "GET /api/v1/ml/report", "GET /api/v1/mm/status"]} />
        <NotIntegrated title="Training & Deployment" stage={3} testId="nl-training"
          sources={["GET /api/v1/training/runs", "GET /api/v1/training/compare", "POST /api/v1/training/rollback"]}>
          <p className="t-note">Nowy model nie zastępuje automatycznie modelu produkcyjnego – wdrożenie LIVE wymaga ręcznej akceptacji (etap 4).</p>
        </NotIntegrated>
      </div>
    </div>);
}
