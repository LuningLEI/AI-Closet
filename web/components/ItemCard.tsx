import { ClothingItem } from "../types";
import { RECOGNITION_SOURCE } from "../lib/constants";

type ItemCardVariant = "list" | "grid";

export default function ItemCard({
  item,
  variant = "list",
  onEdit,
}: {
  item: ClothingItem;
  variant?: ItemCardVariant;
  onEdit?: (item: ClothingItem) => void;
}) {
  const isAnalyzing = item.recognition_source === RECOGNITION_SOURCE.ANALYZING;

  if (variant === "grid") {
    return <GridItemCard item={item} isAnalyzing={isAnalyzing} onEdit={onEdit} />;
  }

  if (isAnalyzing) {
    return (
      <article className="item-card analyzing">
        <div className="item-card-image">
          <img src={item.image_url} alt="Uploaded garment awaiting recognition" />
        </div>
        <div className="item-card-body">
          <div className="item-card-header">
            <div>
              <p className="item-kicker loading-label">Analyzing</p>
              <h3>Reading garment details</h3>
            </div>
            <span className="pill subtle inline-status">
              <span className="loading-dot" />
              Vision
            </span>
          </div>
          <div className="skeleton-stack" aria-label="Recognition loading">
            <span className="skeleton-line wide" />
            <span className="skeleton-line" />
            <span className="skeleton-line short" />
          </div>
          <dl className="item-metadata skeleton-metadata">
            {["Catalog", "Season", "Style", "Occasion"].map((label) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  <span className="skeleton-line mini" />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </article>
    );
  }

  return (
    <article className="item-card">
      <div className="item-card-image">
        <img src={item.image_url} alt={`${item.color} ${item.subtype ?? item.category}`} />
      </div>
      <div className="item-card-body">
        <div className="item-card-header">
          <div>
            <p className="item-kicker">{item.category}</p>
            <h3>{item.subtype ?? item.category}</h3>
          </div>
          <div className="card-actions">
            <span className="pill subtle">{item.color}</span>
            {onEdit && (
              <button className="text-button" type="button" onClick={() => onEdit(item)}>
                Edit
              </button>
            )}
          </div>
        </div>
        <p className="item-summary">{item.recognition_summary ?? "No model summary recorded yet."}</p>
        <dl className="item-metadata">
          <div>
            <dt>Season</dt>
            <dd>{item.season}</dd>
          </div>
          <div>
            <dt>Style</dt>
            <dd>{item.style}</dd>
          </div>
          <div>
            <dt>Occasion</dt>
            <dd>{item.occasion}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{item.recognition_source ?? RECOGNITION_SOURCE.MANUAL}</dd>
          </div>
        </dl>
      </div>
    </article>
  );
}

function GridItemCard({
  item,
  isAnalyzing,
  onEdit,
}: {
  item: ClothingItem;
  isAnalyzing: boolean;
  onEdit?: (item: ClothingItem) => void;
}) {
  return (
    <article className={`flip-card${isAnalyzing ? " analyzing" : ""}`} tabIndex={0}>
      <div className="flip-card-inner">
        <div className="flip-card-face flip-card-front">
          <img src={item.image_url} alt={isAnalyzing ? "Uploaded garment awaiting recognition" : `${item.color} ${item.subtype ?? item.category}`} />
          <div className="flip-card-overlay">
            {isAnalyzing ? (
              <>
                <p className="item-kicker loading-label">Analyzing</p>
                <h3>Reading details</h3>
              </>
            ) : (
              <>
                <p className="item-kicker">{item.category}</p>
                <h3>{item.subtype ?? item.category}</h3>
                <span className="pill subtle">{item.color}</span>
              </>
            )}
          </div>
        </div>
        <div className="flip-card-face flip-card-back">
          {isAnalyzing ? (
            <>
              <div>
                <p className="item-kicker loading-label">Analyzing</p>
                <h3>OpenAI Vision is working</h3>
              </div>
              <div className="skeleton-stack" aria-label="Recognition loading">
                <span className="skeleton-line wide" />
                <span className="skeleton-line" />
                <span className="skeleton-line short" />
              </div>
            </>
          ) : (
            <>
              <div>
                <p className="item-kicker">{item.category}</p>
                <h3>{item.subtype ?? item.category}</h3>
              </div>
              {onEdit && (
                <button className="button secondary compact-button" type="button" onClick={() => onEdit(item)}>
                  Edit
                </button>
              )}
              <p className="item-summary">{item.recognition_summary ?? "No model summary recorded yet."}</p>
              <dl className="flip-metadata">
                <div>
                  <dt>Season</dt>
                  <dd>{item.season}</dd>
                </div>
                <div>
                  <dt>Style</dt>
                  <dd>{item.style}</dd>
                </div>
                <div>
                  <dt>Occasion</dt>
                  <dd>{item.occasion}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>{item.recognition_source ?? RECOGNITION_SOURCE.MANUAL}</dd>
                </div>
              </dl>
            </>
          )}
        </div>
      </div>
    </article>
  );
}
