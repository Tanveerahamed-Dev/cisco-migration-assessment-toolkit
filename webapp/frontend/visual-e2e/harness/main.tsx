import { createElement, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { DemoDataProvider } from "assesshub-frontend";
import config from "../../../../.design-sync/config.json";
import "../../src/theme.css";
import "../../src/styles.css";
import "./harness.css";

type PreviewModule = Record<string, unknown>;
type CardMode = "grid" | "column" | "single";
type CardOverride = {
  cardMode?: CardMode | string;
  primaryStory?: string;
  viewport?: string;
};

const previewModules = import.meta.glob<PreviewModule>(
  "../../../../.design-sync/previews/*.tsx",
  { eager: true },
);

const modulesByComponent = new Map<string, PreviewModule>();
for (const [path, module] of Object.entries(previewModules)) {
  const name = path.match(/\/([^/]+)\.tsx$/)?.[1];
  if (name) modulesByComponent.set(name, module);
}

const configuredComponents = Object.keys(config.componentSrcMap).sort();
const requested = new URLSearchParams(window.location.search).get("component") || "";
const preview = modulesByComponent.get(requested);
const root = createRoot(document.getElementById("root")!);

function fail(message: string) {
  (window as any).__VISUAL_HARNESS__ = { error: message };
  root.render(<pre className="visual-error" data-testid="harness-error">{message}</pre>);
}

if (!requested) {
  fail(`Missing ?component=. Configured components: ${configuredComponents.join(", ")}`);
} else if (!configuredComponents.includes(requested)) {
  fail(`Unknown component ${requested}. Configured components: ${configuredComponents.join(", ")}`);
} else if (!preview) {
  fail(`No tracked preview module found for configured component ${requested}.`);
} else {
  const variants = Object.entries(preview)
    .filter(([name, value]) => /^[A-Z]/.test(name) && typeof value === "function")
    .sort(([left], [right]) => left.localeCompare(right)) as Array<[string, ComponentType]>;

  if (!variants.length) {
    fail(`Preview ${requested}.tsx has no PascalCase component exports.`);
  } else {
    const override = (config.overrides as Record<string, CardOverride>)[requested] || {};
    const rawMode = override.cardMode;
    const viewportMatch = override.viewport?.match(/^([1-9]\d*)x([1-9]\d*)$/);
    if (rawMode && rawMode !== "column" && rawMode !== "single") {
      fail(`Unsupported cardMode "${rawMode}" for ${requested}.`);
    } else if (override.primaryStory && !variants.some(([name]) => name === override.primaryStory)) {
      fail(`Unknown primaryStory "${override.primaryStory}" for ${requested}.`);
    } else if (override.viewport && !viewportMatch) {
      fail(`Invalid viewport "${override.viewport}" for ${requested}; expected WIDTHxHEIGHT.`);
    } else {
      const mode = (rawMode || "grid") as CardMode;
      const viewport = viewportMatch
        ? `${Math.min(Number(viewportMatch[1]), 2000)}x${Math.min(Number(viewportMatch[2]), 2000)}`
        : "900x700";
      const primaryStory = override.primaryStory || null;
      const orderedVariants = [...variants];
      if (mode === "column" && primaryStory) {
        const primaryIndex = orderedVariants.findIndex(([name]) => name === primaryStory);
        if (primaryIndex > 0) {
          orderedVariants.unshift(orderedVariants.splice(primaryIndex, 1)[0]);
        }
      }
      const selectedVariant = orderedVariants.find(([name]) => name === primaryStory)
        || orderedVariants[0]!;
      const renderedVariants = mode === "single" ? [selectedVariant] : orderedVariants;
      (window as any).__VISUAL_HARNESS__ = {
        component: requested,
        components: configuredComponents,
        variants: variants.map(([name]) => name),
        renderedVariants: renderedVariants.map(([name]) => name),
        mode,
        primaryStory,
        viewport,
      };

      root.render(
        <main
          className="visual-card"
          data-testid="design-card"
          data-component={requested}
          data-mode={mode}
          data-variant-count={renderedVariants.length}
          data-viewport={viewport}
        >
          <div className={mode === "single" ? "ds-single" : `ds-grid${mode === "column" ? " ds-col" : ""}`}>
            {renderedVariants.map(([name, Variant]) => mode === "single" ? (
              <div className="ds-variant" data-variant={name} key={name}>
                <DemoDataProvider>{createElement(Variant)}</DemoDataProvider>
              </div>
            ) : (
              <section className="ds-cell ds-variant" data-variant={name} key={name}>
                <h4>{name}</h4>
                <div className="ds-story">
                  <DemoDataProvider>{createElement(Variant)}</DemoDataProvider>
                </div>
              </section>
            ))}
          </div>
        </main>,
      );
    }
  }
}
