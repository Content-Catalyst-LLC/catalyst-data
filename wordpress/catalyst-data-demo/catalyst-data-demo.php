<?php
/**
 * Plugin Name: Catalyst Data Demo
 * Description: Browser-based demo for the Catalyst Data module. Adds the [catalyst_data_demo] shortcode.
 * Version: 1.0.1
 * Author: Content Catalyst LLC
 * License: MIT
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if (!defined('ABSPATH')) {
    exit;
}

define('CATALYST_DATA_DEMO_VERSION', '1.0.1');

function catalyst_data_demo_register_assets() {
    $base_url = plugin_dir_url(__FILE__);
    wp_register_style(
        'catalyst-data-demo-style',
        $base_url . 'assets/catalyst-data-demo.css',
        array(),
        CATALYST_DATA_DEMO_VERSION
    );
    wp_register_script(
        'catalyst-data-demo-contract',
        $base_url . 'assets/catalyst-data-contract.js',
        array(),
        CATALYST_DATA_DEMO_VERSION,
        true
    );
    wp_register_script(
        'catalyst-data-demo-script',
        $base_url . 'assets/catalyst-data-demo.js',
        array('catalyst-data-demo-contract'),
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
    wp_enqueue_script('catalyst-data-demo-contract');
    wp_enqueue_script('catalyst-data-demo-script');

    ob_start();
    ?>
    <section class="cdata-demo" data-catalyst-data-demo>
        <header class="cdata-demo__header">
            <p class="cdata-demo__eyebrow">Catalyst Data Live Demo</p>
            <h2>Build a Traceable Measurement Record</h2>
            <p>
                Use this demo to connect an entity, indicator, reporting period, measurement, source, and confidence level.
                The output shows how Catalyst Data turns raw measurement work into a reviewable evidence record.
            </p>
        </header>

        <div class="cdata-demo__grid">
            <form class="cdata-demo__form" aria-label="Catalyst Data demo form">
                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-entity">Entity or project</label>
                    <input id="<?php echo esc_attr($id); ?>-entity" name="entity" type="text" value="Urban Tree Canopy Program" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-type">Entity type</label>
                    <select id="<?php echo esc_attr($id); ?>-type" name="entityType">
                        <option value="project" selected>Project</option>
                        <option value="organization">Organization</option>
                        <option value="program">Program</option>
                        <option value="site">Site</option>
                        <option value="policy">Policy</option>
                    </select>
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
                    <label for="<?php echo esc_attr($id); ?>-period">Reporting period</label>
                    <select id="<?php echo esc_attr($id); ?>-period" name="period">
                        <option value="2026-Q1">2026-Q1</option>
                        <option value="2026-Q2" selected>2026-Q2</option>
                        <option value="2026-Q3">2026-Q3</option>
                        <option value="2026-Q4">2026-Q4</option>
                        <option value="2026">2026 annual</option>
                    </select>
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-baseline">Baseline value</label>
                    <input id="<?php echo esc_attr($id); ?>-baseline" name="baseline" type="number" step="0.01" value="62" />
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-current">Current value</label>
                    <input id="<?php echo esc_attr($id); ?>-current" name="current" type="number" step="0.01" value="78" />
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
                    </select>
                </div>

                <div class="cdata-demo__field">
                    <label for="<?php echo esc_attr($id); ?>-confidence">Confidence</label>
                    <input id="<?php echo esc_attr($id); ?>-confidence" name="confidence" type="range" min="0" max="100" value="72" />
                    <output class="cdata-demo__confidence" data-confidence-output>72%</output>
                </div>

                <div class="cdata-demo__field cdata-demo__field--wide">
                    <label for="<?php echo esc_attr($id); ?>-notes">Method and assumption notes</label>
                    <textarea id="<?php echo esc_attr($id); ?>-notes" name="notes" rows="4">Current value combines verified site records with program-reported updates. Confidence is moderate because not all sites have third-party verification.</textarea>
                </div>

                <div class="cdata-demo__actions">
                    <button type="button" class="cdata-demo__button" data-cdata-sample>Load sample</button>
                    <button type="button" class="cdata-demo__button cdata-demo__button--dark" data-cdata-copy>Copy JSON</button>
                    <button type="button" class="cdata-demo__button" data-cdata-download>Download JSON</button>
                </div>
            </form>

            <aside class="cdata-demo__output" aria-live="polite">
                <p class="cdata-demo__output-label">Generated evidence record</p>
                <h3 data-cdata-title>Urban Tree Canopy Program</h3>

                <div class="cdata-demo__stat-grid">
                    <div><span>Change</span><strong data-cdata-change>—</strong></div>
                    <div><span>Confidence</span><strong data-cdata-confidence>—</strong></div>
                    <div><span>Review status</span><strong data-cdata-status>—</strong></div>
                    <div><span>Signal status</span><strong data-cdata-signal>—</strong></div>
                </div>

                <div class="cdata-demo__trace">
                    <strong>Trace path</strong>
                    <span data-cdata-trace>entity → indicator → period → measurement → source → confidence → review</span>
                </div>

                <div class="cdata-demo__brief" data-cdata-brief></div>

                <label class="cdata-demo__json-label" for="<?php echo esc_attr($id); ?>-json-output">Structured JSON export</label>
                <textarea id="<?php echo esc_attr($id); ?>-json-output" class="cdata-demo__json" data-cdata-json rows="12" readonly></textarea>
            </aside>
        </div>

        <footer class="cdata-demo__footer">
            <strong>Boundary:</strong> this demo is educational and browser-based. It does not certify compliance, verify impact, or replace professional review.
        </footer>
    </section>
    <?php
    return ob_get_clean();
}
add_shortcode('catalyst_data_demo', 'catalyst_data_demo_shortcode');
