<?php
/**
 * Plugin Name: Catalyst Data Demo
 * Description: Browser-based canonical Catalyst Data record demo. Adds the [catalyst_data_demo] shortcode.
 * Version: 1.7.0
 * Author: Content Catalyst LLC
 * License: MIT
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if (!defined('ABSPATH')) {
    exit;
}

define('CATALYST_DATA_DEMO_VERSION', '1.7.0');

function catalyst_data_demo_register_assets() {
    $base_url = plugin_dir_url(__FILE__);
    wp_register_style(
        'catalyst-data-demo-style',
        $base_url . 'assets/catalyst-data-demo.css',
        array(),
        CATALYST_DATA_DEMO_VERSION
    );
    wp_register_script(
        'catalyst-data-demo-review-contract',
        $base_url . 'assets/catalyst-data-contract.js',
        array(),
        CATALYST_DATA_DEMO_VERSION,
        true
    );
    wp_register_script(
        'catalyst-data-demo-record-contract',
        $base_url . 'assets/catalyst-data-record-contract.js',
        array('catalyst-data-demo-review-contract'),
        CATALYST_DATA_DEMO_VERSION,
        true
    );
    wp_register_script(
        'catalyst-data-demo-script',
        $base_url . 'assets/catalyst-data-demo.js',
        array('catalyst-data-demo-record-contract'),
        CATALYST_DATA_DEMO_VERSION,
        true
    );
}
add_action('wp_enqueue_scripts', 'catalyst_data_demo_register_assets');

function catalyst_data_demo_shortcode($atts = array()) {
    static $instance = 0;
    $instance++;
    $id = 'cdata-' . $instance;

    wp_enqueue_style('catalyst-data-demo-style');
    wp_enqueue_script('catalyst-data-demo-review-contract');
    wp_enqueue_script('catalyst-data-demo-record-contract');
    wp_enqueue_script('catalyst-data-demo-script');

    ob_start();
    ?>
    <section class="cdata-demo" data-catalyst-data-demo>
        <header class="cdata-demo__header">
            <p class="cdata-demo__eyebrow">Catalyst Data Record 1.0</p>
            <h2>Build a Canonical Evidence Record</h2>
            <p>
                Create a versioned measurement record with stable identifiers, source provenance, method limitations,
                confidence, and review metadata. The generated JSON follows <code>catalyst-data-record/1.0</code>.
            </p>
        </header>

        <div class="cdata-demo__grid">
            <form class="cdata-demo__form" aria-label="Catalyst Data canonical record form">
                <div class="cdata-demo__section-title">Entity and indicator</div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-entity">Entity or project</label>
                    <input id="<?php echo esc_attr($id); ?>-entity" name="entity" type="text" value="Urban Tree Canopy Program" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-type">Entity type</label>
                    <select id="<?php echo esc_attr($id); ?>-type" name="entityType">
                        <option value="country">Country</option>
                        <option value="organization">Organization</option>
                        <option value="project" selected>Project</option>
                        <option value="program">Program</option>
                        <option value="site">Site</option>
                        <option value="policy">Policy</option>
                        <option value="persona">Persona</option>
                        <option value="experiment">Experiment</option>
                        <option value="dataset">Dataset</option>
                        <option value="other">Other</option>
                    </select>
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-external-id">External ID</label>
                    <input id="<?php echo esc_attr($id); ?>-external-id" name="externalId" type="text" value="urban-tree-canopy" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-indicator">Indicator</label>
                    <select id="<?php echo esc_attr($id); ?>-indicator" name="indicator">
                        <option value="Data completeness score" data-unit="score" selected>Data completeness score</option>
                        <option value="Estimated CO2e avoided" data-unit="tCO2e">Estimated CO2e avoided</option>
                        <option value="Energy intensity" data-unit="kWh / sq ft">Energy intensity</option>
                        <option value="Participation rate" data-unit="%">Participation rate</option>
                        <option value="Source coverage" data-unit="%">Source coverage</option>
                    </select>
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-unit">Unit</label>
                    <input id="<?php echo esc_attr($id); ?>-unit" name="unit" type="text" value="score" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-direction">Better direction</label>
                    <select id="<?php echo esc_attr($id); ?>-direction" name="direction">
                        <option value="higher" selected>Higher is better</option>
                        <option value="lower">Lower is better</option>
                        <option value="neutral">Neutral / descriptive</option>
                    </select>
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-indicator-version">Indicator version</label>
                    <input id="<?php echo esc_attr($id); ?>-indicator-version" name="indicatorVersion" type="text" value="1.0" />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-framework">Framework</label>
                    <input id="<?php echo esc_attr($id); ?>-framework" name="framework" type="text" value="Sustainable Catalyst Evidence Readiness" />
                </div>

                <div class="cdata-demo__section-title">Period and measurement</div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-period">Reporting period</label>
                    <input id="<?php echo esc_attr($id); ?>-period" name="period" type="text" value="2026-Q2" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-period-start">Period start</label>
                    <input id="<?php echo esc_attr($id); ?>-period-start" name="periodStart" type="date" value="2026-04-01" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-period-end">Period end</label>
                    <input id="<?php echo esc_attr($id); ?>-period-end" name="periodEnd" type="date" value="2026-06-30" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-baseline">Baseline value</label>
                    <input id="<?php echo esc_attr($id); ?>-baseline" name="baseline" type="number" step="0.01" value="62" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-current">Current value</label>
                    <input id="<?php echo esc_attr($id); ?>-current" name="current" type="number" step="0.01" value="78" />
                </div>

                <div class="cdata-demo__section-title">Source provenance</div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-source">Source</label>
                    <input id="<?php echo esc_attr($id); ?>-source" name="source" type="text" value="Internal program tracker + field verification notes" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-source-type">Source type</label>
                    <select id="<?php echo esc_attr($id); ?>-source-type" name="sourceType">
                        <option value="internal record" selected>Internal record</option>
                        <option value="third-party dataset">Third-party dataset</option>
                        <option value="survey">Survey</option>
                        <option value="public registry">Public registry</option>
                        <option value="model estimate">Model estimate</option>
                        <option value="publication">Publication</option>
                        <option value="sensor">Sensor</option>
                        <option value="api">API</option>
                        <option value="other">Other</option>
                        <option value="unspecified">Unspecified</option>
                    </select>
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-publisher">Publisher</label>
                    <input id="<?php echo esc_attr($id); ?>-publisher" name="sourcePublisher" type="text" value="Content Catalyst LLC" />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-source-url">Source URL</label>
                    <input id="<?php echo esc_attr($id); ?>-source-url" name="sourceUrl" type="url" value="https://sustainablecatalyst.com/records/urban-tree-canopy-2026-q2" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-source-license">License</label>
                    <input id="<?php echo esc_attr($id); ?>-source-license" name="sourceLicense" type="text" value="Internal review record" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-retrieved">Retrieved at</label>
                    <input id="<?php echo esc_attr($id); ?>-retrieved" name="retrievedAt" type="datetime-local" value="2026-07-16T11:30" />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-citation">Citation</label>
                    <textarea id="<?php echo esc_attr($id); ?>-citation" name="citation" rows="2">Content Catalyst LLC. Urban Tree Canopy Program tracker and field verification notes, 2026-Q2.</textarea>
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-checksum">Source checksum</label>
                    <input id="<?php echo esc_attr($id); ?>-checksum" name="checksum" type="text" value="sha256:7c7d2ab0857f139ee840678101daa9baaaae77f0e5aa7adf9f6ca5ac2e8f1f4a" />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-access-notes">Access notes</label>
                    <input id="<?php echo esc_attr($id); ?>-access-notes" name="accessNotes" type="text" value="Public example derived from a fictional program record." />
                </div>

                <div class="cdata-demo__section-title">Confidence, method, and review</div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-confidence">Confidence</label>
                    <input id="<?php echo esc_attr($id); ?>-confidence" name="confidence" type="range" min="0" max="100" value="72" />
                    <output class="cdata-demo__confidence" data-confidence-output>72%</output>
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-quality-flags">Quality flags</label>
                    <input id="<?php echo esc_attr($id); ?>-quality-flags" name="qualityFlags" type="text" value="unverified" />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-confidence-basis">Confidence basis</label>
                    <input id="<?php echo esc_attr($id); ?>-confidence-basis" name="confidenceBasis" type="text" value="Verified site records plus partial field review." />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-notes">Method notes</label>
                    <textarea id="<?php echo esc_attr($id); ?>-notes" name="notes" rows="3">Current value combines verified site records with program-reported updates.</textarea>
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-assumptions">Assumptions</label>
                    <textarea id="<?php echo esc_attr($id); ?>-assumptions" name="assumptions" rows="2">Program-reported site updates use the same completeness rubric as the baseline.</textarea>
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-limitations">Limitations</label>
                    <textarea id="<?php echo esc_attr($id); ?>-limitations" name="limitations" rows="2">Not all sites have independent third-party verification.</textarea>
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-uncertainty">Uncertainty</label>
                    <input id="<?php echo esc_attr($id); ?>-uncertainty" name="uncertainty" type="text" value="Moderate uncertainty remains for unverified sites." />
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-reviewer-notes">Reviewer notes</label>
                    <textarea id="<?php echo esc_attr($id); ?>-reviewer-notes" name="reviewerNotes" rows="2">Suitable for internal comparison with a visible verification limitation.</textarea>
                </div>

                <p class="cdata-demo__error" data-cdata-error hidden></p>

                <div class="cdata-demo__actions">
                    <button type="button" class="cdata-demo__button" data-cdata-sample>Load sample</button>
                    <button type="button" class="cdata-demo__button cdata-demo__button--dark" data-cdata-copy>Copy JSON</button>
                    <button type="button" class="cdata-demo__button" data-cdata-download>Download JSON</button>
                </div>
            </form>

            <aside class="cdata-demo__output" aria-live="polite">
                <p class="cdata-demo__output-label">Canonical evidence record</p>
                <h3 data-cdata-title>Urban Tree Canopy Program</h3>

                <div class="cdata-demo__record-id">
                    <span>Stable record ID</span>
                    <code data-cdata-record-id>—</code>
                </div>

                <div class="cdata-demo__stat-grid">
                    <div><span>Change</span><strong data-cdata-change>—</strong></div>
                    <div><span>Confidence</span><strong data-cdata-confidence>—</strong></div>
                    <div><span>Review status</span><strong data-cdata-status>—</strong></div>
                    <div><span>Signal status</span><strong data-cdata-signal>—</strong></div>
                </div>

                <div class="cdata-demo__trace">
                    <strong>Canonical contract</strong>
                    <span>catalyst-data-record/1.0</span>
                </div>

                <div class="cdata-demo__brief" data-cdata-brief></div>

                <label class="cdata-demo__json-label" for="<?php echo esc_attr($id); ?>-json-output">Structured JSON export</label>
                <textarea id="<?php echo esc_attr($id); ?>-json-output" class="cdata-demo__json" data-cdata-json rows="18" readonly></textarea>
            </aside>
        </div>

        <footer class="cdata-demo__footer">
            <strong>Boundary:</strong> the demo validates structure and derived contract logic in the browser. It does not certify source truth, compliance, impact, or professional conclusions.
        </footer>
    </section>
    <?php
    return ob_get_clean();
}
add_shortcode('catalyst_data_demo', 'catalyst_data_demo_shortcode');
