<?php
/**
 * Plugin Name: Sustainable Catalyst Data
 * Description: Governed WordPress integration for Catalyst Data public records, archival intelligence, statistics, environmental and space-science data, canonical entities, and connected cross-source graph federation.
 * Version: 3.0.0
 * Author: Content Catalyst LLC
 * License: MIT
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if (!defined('ABSPATH')) {
    exit;
}

define('SUSTAINABLE_CATALYST_DATA_VERSION', '3.0.0');
define('SUSTAINABLE_CATALYST_DATA_OPTION_API', 'sustainable_catalyst_data_api_base_url');
define('SUSTAINABLE_CATALYST_DATA_OPTION_TIMEOUT', 'sustainable_catalyst_data_timeout');
define('SUSTAINABLE_CATALYST_DATA_OPTION_CACHE', 'sustainable_catalyst_data_cache_ttl');

function sustainable_catalyst_data_activate() {
    add_option(SUSTAINABLE_CATALYST_DATA_OPTION_API, '');
    add_option(SUSTAINABLE_CATALYST_DATA_OPTION_TIMEOUT, 12);
    add_option(SUSTAINABLE_CATALYST_DATA_OPTION_CACHE, 300);
}
register_activation_hook(__FILE__, 'sustainable_catalyst_data_activate');

function sustainable_catalyst_data_api_base_url() {
    return untrailingslashit((string) get_option(SUSTAINABLE_CATALYST_DATA_OPTION_API, ''));
}

function sustainable_catalyst_data_sanitize_api_url($value) {
    $value = untrailingslashit(esc_url_raw(trim((string) $value)));
    if ($value === '') {
        return '';
    }
    $parts = wp_parse_url($value);
    if (!is_array($parts) || empty($parts['scheme']) || empty($parts['host'])) {
        add_settings_error('sustainable_catalyst_data', 'invalid_api_url', 'Catalyst Data API URL must be an absolute URL.');
        return (string) get_option(SUSTAINABLE_CATALYST_DATA_OPTION_API, '');
    }
    $scheme = strtolower((string) $parts['scheme']);
    $host = strtolower((string) $parts['host']);
    $local = in_array($host, array('localhost', '127.0.0.1', '::1'), true);
    if ($scheme !== 'https' && !($local && $scheme === 'http')) {
        add_settings_error('sustainable_catalyst_data', 'insecure_api_url', 'Use HTTPS for the Catalyst Data API. HTTP is allowed only for localhost development.');
        return (string) get_option(SUSTAINABLE_CATALYST_DATA_OPTION_API, '');
    }
    if (!empty($parts['user']) || !empty($parts['pass']) || !empty($parts['query']) || !empty($parts['fragment'])) {
        add_settings_error('sustainable_catalyst_data', 'unsafe_api_url', 'API base URL must not contain credentials, query parameters, or fragments.');
        return (string) get_option(SUSTAINABLE_CATALYST_DATA_OPTION_API, '');
    }
    return $value;
}

function sustainable_catalyst_data_register_settings() {
    register_setting('sustainable_catalyst_data', SUSTAINABLE_CATALYST_DATA_OPTION_API, array(
        'type' => 'string',
        'sanitize_callback' => 'sustainable_catalyst_data_sanitize_api_url',
        'default' => '',
    ));
    register_setting('sustainable_catalyst_data', SUSTAINABLE_CATALYST_DATA_OPTION_TIMEOUT, array(
        'type' => 'integer',
        'sanitize_callback' => function ($value) { return max(2, min(30, absint($value))); },
        'default' => 12,
    ));
    register_setting('sustainable_catalyst_data', SUSTAINABLE_CATALYST_DATA_OPTION_CACHE, array(
        'type' => 'integer',
        'sanitize_callback' => function ($value) { return max(30, min(3600, absint($value))); },
        'default' => 300,
    ));
}
add_action('admin_init', 'sustainable_catalyst_data_register_settings');

function sustainable_catalyst_data_admin_menu() {
    add_options_page('Catalyst Data', 'Catalyst Data', 'manage_options', 'sustainable-catalyst-data', 'sustainable_catalyst_data_settings_page');
}
add_action('admin_menu', 'sustainable_catalyst_data_admin_menu');

function sustainable_catalyst_data_fetch($path, $query = array(), $cache_ttl = null) {
    $base = sustainable_catalyst_data_api_base_url();
    if ($base === '') {
        return new WP_Error('catalyst_data_unconfigured', 'Catalyst Data API is not configured.', array('status' => 503));
    }
    $path = '/' . ltrim((string) $path, '/');
    $url = $base . $path;
    if (!empty($query)) {
        $url = add_query_arg($query, $url);
    }
    $ttl = $cache_ttl === null ? absint(get_option(SUSTAINABLE_CATALYST_DATA_OPTION_CACHE, 300)) : absint($cache_ttl);
    $cache_key = 'scd_' . md5($url);
    if ($ttl > 0) {
        $cached = get_transient($cache_key);
        if (is_array($cached)) {
            $cached['_catalyst_cache'] = true;
            return $cached;
        }
    }
    $response = wp_safe_remote_get($url, array(
        'timeout' => max(2, min(30, absint(get_option(SUSTAINABLE_CATALYST_DATA_OPTION_TIMEOUT, 12)))),
        'redirection' => 3,
        'user-agent' => 'SustainableCatalystDataWordPress/' . SUSTAINABLE_CATALYST_DATA_VERSION . '; ' . home_url('/'),
        'headers' => array('Accept' => 'application/json'),
        'limit_response_size' => 2097152,
    ));
    if (is_wp_error($response)) {
        return new WP_Error('catalyst_data_upstream_error', $response->get_error_message(), array('status' => 502));
    }
    $status = (int) wp_remote_retrieve_response_code($response);
    $body = (string) wp_remote_retrieve_body($response);
    $payload = json_decode($body, true);
    if ($status < 200 || $status >= 300) {
        $message = is_array($payload) && !empty($payload['message']) ? (string) $payload['message'] : 'Catalyst Data API returned HTTP ' . $status . '.';
        return new WP_Error('catalyst_data_http_error', $message, array('status' => $status));
    }
    if (!is_array($payload)) {
        return new WP_Error('catalyst_data_invalid_json', 'Catalyst Data API returned invalid JSON.', array('status' => 502));
    }
    if ($ttl > 0) {
        set_transient($cache_key, $payload, $ttl);
    }
    return $payload;
}

function sustainable_catalyst_data_health() {
    $payload = sustainable_catalyst_data_fetch('/health', array(), 30);
    if (is_wp_error($payload)) {
        return $payload;
    }
    $payload['wordpress_integration_version'] = SUSTAINABLE_CATALYST_DATA_VERSION;
    return $payload;
}

function sustainable_catalyst_data_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    $health = sustainable_catalyst_data_health();
    ?>
    <div class="wrap">
        <h1>Catalyst Data</h1>
        <p>Configure the public Catalyst Data API used by Sustainable Catalyst WordPress surfaces. Database credentials and private API tokens do not belong in WordPress.</p>
        <?php settings_errors('sustainable_catalyst_data'); ?>
        <form method="post" action="options.php">
            <?php settings_fields('sustainable_catalyst_data'); ?>
            <table class="form-table" role="presentation">
                <tr><th scope="row"><label for="scd-api-url">Catalyst Data API base URL</label></th><td><input class="regular-text code" id="scd-api-url" type="url" name="<?php echo esc_attr(SUSTAINABLE_CATALYST_DATA_OPTION_API); ?>" value="<?php echo esc_attr(sustainable_catalyst_data_api_base_url()); ?>" placeholder="https://data.sustainablecatalyst.com" /><p class="description">HTTPS production endpoint only. Do not enter PostgreSQL URLs or bearer tokens.</p></td></tr>
                <tr><th scope="row"><label for="scd-timeout">Request timeout</label></th><td><input id="scd-timeout" type="number" min="2" max="30" name="<?php echo esc_attr(SUSTAINABLE_CATALYST_DATA_OPTION_TIMEOUT); ?>" value="<?php echo esc_attr(get_option(SUSTAINABLE_CATALYST_DATA_OPTION_TIMEOUT, 12)); ?>" /> seconds</td></tr>
                <tr><th scope="row"><label for="scd-cache">Public cache TTL</label></th><td><input id="scd-cache" type="number" min="30" max="3600" name="<?php echo esc_attr(SUSTAINABLE_CATALYST_DATA_OPTION_CACHE); ?>" value="<?php echo esc_attr(get_option(SUSTAINABLE_CATALYST_DATA_OPTION_CACHE, 300)); ?>" /> seconds</td></tr>
            </table>
            <?php submit_button(); ?>
        </form>
        <h2>Connection health</h2>
        <?php if (is_wp_error($health)) : ?>
            <div class="notice notice-warning inline"><p><strong>Unavailable:</strong> <?php echo esc_html($health->get_error_message()); ?></p></div>
        <?php else : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>Status</th><td><?php echo esc_html(isset($health['status']) ? $health['status'] : 'unknown'); ?></td></tr>
                <tr><th>Catalyst Data version</th><td><?php echo esc_html(isset($health['version']) ? $health['version'] : 'unknown'); ?></td></tr>
                <tr><th>Database backend</th><td><?php echo esc_html(isset($health['database_backend']) ? $health['database_backend'] : 'unknown'); ?></td></tr>
                <tr><th>Migration</th><td><?php echo esc_html((isset($health['migration_version']) ? $health['migration_version'] : '?') . ' / ' . (isset($health['latest_migration']) ? $health['latest_migration'] : '?')); ?></td></tr>
                <tr><th>Public records</th><td><?php echo esc_html(isset($health['record_count']) ? $health['record_count'] : 'unknown'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>Archive intelligence</h2>
        <?php $archive = sustainable_catalyst_data_fetch('/v1/archive/status', array(), 30); ?>
        <?php if (!is_wp_error($archive)) : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>Internet Archive items</th><td><?php echo esc_html(isset($archive['item_count']) ? $archive['item_count'] : '0'); ?></td></tr>
                <tr><th>Cataloged files</th><td><?php echo esc_html(isset($archive['file_count']) ? $archive['file_count'] : '0'); ?></td></tr>
                <tr><th>Archived searches</th><td><?php echo esc_html(isset($archive['search_count']) ? $archive['search_count'] : '0'); ?></td></tr>
                <tr><th>Wayback captures</th><td><?php echo esc_html(isset($archive['wayback_capture_count']) ? $archive['wayback_capture_count'] : '0'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>Global statistics</h2>
        <?php $statistics = sustainable_catalyst_data_fetch('/v1/statistics/status', array(), 30); ?>
        <?php if (!is_wp_error($statistics)) : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>World Bank countries</th><td><?php echo esc_html(isset($statistics['world_bank_country_count']) ? $statistics['world_bank_country_count'] : '0'); ?></td></tr>
                <tr><th>World Bank indicators</th><td><?php echo esc_html(isset($statistics['world_bank_indicator_count']) ? $statistics['world_bank_indicator_count'] : '0'); ?></td></tr>
                <tr><th>World Bank observations</th><td><?php echo esc_html(isset($statistics['world_bank_observation_count']) ? $statistics['world_bank_observation_count'] : '0'); ?></td></tr>
                <tr><th>UN SDG geographies</th><td><?php echo esc_html(isset($statistics['un_sdg_geoarea_count']) ? $statistics['un_sdg_geoarea_count'] : '0'); ?></td></tr>
                <tr><th>UN SDG indicators</th><td><?php echo esc_html(isset($statistics['un_sdg_indicator_count']) ? $statistics['un_sdg_indicator_count'] : '0'); ?></td></tr>
                <tr><th>UN SDG observations</th><td><?php echo esc_html(isset($statistics['un_sdg_observation_count']) ? $statistics['un_sdg_observation_count'] : '0'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>U.S. public data</h2>
        <?php $us_public = sustainable_catalyst_data_fetch('/v1/us-public/status', array(), 30); ?>
        <?php if (!is_wp_error($us_public)) : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>Census observations</th><td><?php echo esc_html(isset($us_public['census_observation_count']) ? $us_public['census_observation_count'] : '0'); ?></td></tr>
                <tr><th>BLS series / observations</th><td><?php echo esc_html((isset($us_public['bls_series_count']) ? $us_public['bls_series_count'] : '0') . ' / ' . (isset($us_public['bls_observation_count']) ? $us_public['bls_observation_count'] : '0')); ?></td></tr>
                <tr><th>BEA observations</th><td><?php echo esc_html(isset($us_public['bea_observation_count']) ? $us_public['bea_observation_count'] : '0'); ?></td></tr>
                <tr><th>EIA observations</th><td><?php echo esc_html(isset($us_public['eia_observation_count']) ? $us_public['eia_observation_count'] : '0'); ?></td></tr>
                <tr><th>EPA records</th><td><?php echo esc_html(isset($us_public['epa_record_count']) ? $us_public['epa_record_count'] : '0'); ?></td></tr>
                <tr><th>USGS water observations</th><td><?php echo esc_html(isset($us_public['usgs_observation_count']) ? $us_public['usgs_observation_count'] : '0'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>Shortcodes</h2>
        <h2>Earth, climate &amp; ocean network</h2>
        <?php $earth = sustainable_catalyst_data_fetch('/v1/earth/status', array(), 30); ?>
        <?php if (!is_wp_error($earth)) : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>NOAA NCEI observations</th><td><?php echo esc_html(isset($earth['ncei_observation_count']) ? $earth['ncei_observation_count'] : '0'); ?></td></tr>
                <tr><th>ERDDAP datasets / observations</th><td><?php echo esc_html((isset($earth['erddap_dataset_count']) ? $earth['erddap_dataset_count'] : '0') . ' / ' . (isset($earth['erddap_observation_count']) ? $earth['erddap_observation_count'] : '0')); ?></td></tr>
                <tr><th>IOOS datasets</th><td><?php echo esc_html(isset($earth['ioos_dataset_count']) ? $earth['ioos_dataset_count'] : '0'); ?></td></tr>
                <tr><th>USGS earthquakes</th><td><?php echo esc_html(isset($earth['usgs_earthquake_count']) ? $earth['usgs_earthquake_count'] : '0'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>Space &amp; scientific network</h2>
        <?php $space = sustainable_catalyst_data_fetch('/v1/space/status', array(), 30); ?>
        <?php if (!is_wp_error($space)) : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>NASA DONKI events</th><td><?php echo esc_html(isset($space['nasa_space_weather_event_count']) ? $space['nasa_space_weather_event_count'] : '0'); ?></td></tr>
                <tr><th>JPL small bodies / NEOs / PHAs</th><td><?php echo esc_html((isset($space['jpl_small_body_count']) ? $space['jpl_small_body_count'] : '0') . ' / ' . (isset($space['jpl_neo_count']) ? $space['jpl_neo_count'] : '0') . ' / ' . (isset($space['jpl_pha_count']) ? $space['jpl_pha_count'] : '0')); ?></td></tr>
                <tr><th>JPL close approaches</th><td><?php echo esc_html(isset($space['jpl_close_approach_count']) ? $space['jpl_close_approach_count'] : '0'); ?></td></tr>
                <tr><th>NASA exoplanets</th><td><?php echo esc_html(isset($space['nasa_exoplanet_count']) ? $space['nasa_exoplanet_count'] : '0'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>Dataset catalog &amp; discovery</h2>
        <?php $catalog = sustainable_catalyst_data_fetch('/v1/catalog/status', array(), 30); ?>
        <?php if (!is_wp_error($catalog)) : ?>
            <table class="widefat striped" style="max-width:760px"><tbody>
                <tr><th>Active datasets / providers</th><td><?php echo esc_html((isset($catalog['active_dataset_count']) ? $catalog['active_dataset_count'] : '0') . ' / ' . (isset($catalog['provider_count']) ? $catalog['provider_count'] : '0')); ?></td></tr>
                <tr><th>Fresh / aging / stale / unknown</th><td><?php echo esc_html((isset($catalog['fresh_count']) ? $catalog['fresh_count'] : '0') . ' / ' . (isset($catalog['aging_count']) ? $catalog['aging_count'] : '0') . ' / ' . (isset($catalog['stale_count']) ? $catalog['stale_count'] : '0') . ' / ' . (isset($catalog['unknown_freshness_count']) ? $catalog['unknown_freshness_count'] : '0')); ?></td></tr>
                <tr><th>Indexed source records</th><td><?php echo esc_html(isset($catalog['indexed_record_count']) ? $catalog['indexed_record_count'] : '0'); ?></td></tr>
                <tr><th>Latest catalog sync</th><td><?php echo esc_html(isset($catalog['latest_sync_at']) && $catalog['latest_sync_at'] ? $catalog['latest_sync_at'] : 'Not synchronized'); ?></td></tr>
            </tbody></table>
        <?php endif; ?>
        <h2>Canonical entities &amp; identifiers</h2>
        <?php $entities = sustainable_catalyst_data_fetch('/v1/entities/status', array(), 30); ?>
        <?php if (!is_wp_error($entities)) : ?>
        <table class="widefat striped"><tbody>
            <tr><th>Active entities / country areas</th><td><?php echo esc_html((isset($entities['active_entity_count']) ? $entities['active_entity_count'] : '0') . ' / ' . (isset($entities['country_area_count']) ? $entities['country_area_count'] : '0')); ?></td></tr>
            <tr><th>Identifiers / namespaces</th><td><?php echo esc_html((isset($entities['identifier_count']) ? $entities['identifier_count'] : '0') . ' / ' . (isset($entities['namespace_count']) ? $entities['namespace_count'] : '0')); ?></td></tr>
            <tr><th>Latest entity sync</th><td><?php echo esc_html(isset($entities['latest_sync_at']) && $entities['latest_sync_at'] ? $entities['latest_sync_at'] : 'Not synchronized'); ?></td></tr>
        </tbody></table>
        <?php endif; ?>
        <h2>Connected data graph</h2>
        <?php $graph = sustainable_catalyst_data_fetch('/v1/graph/status', array(), 30); ?>
        <?php if (!is_wp_error($graph)) : ?>
        <table class="widefat striped" style="max-width:760px"><tbody>
            <tr><th>Active nodes / edges</th><td><?php echo esc_html((isset($graph['active_node_count']) ? $graph['active_node_count'] : '0') . ' / ' . (isset($graph['active_edge_count']) ? $graph['active_edge_count'] : '0')); ?></td></tr>
            <tr><th>Node types / providers</th><td><?php echo esc_html((isset($graph['node_type_count']) ? $graph['node_type_count'] : '0') . ' / ' . (isset($graph['provider_count']) ? $graph['provider_count'] : '0')); ?></td></tr>
            <tr><th>Latest graph sync</th><td><?php echo esc_html(isset($graph['latest_sync_at']) && $graph['latest_sync_at'] ? $graph['latest_sync_at'] : 'Not synchronized'); ?></td></tr>
        </tbody></table>
        <?php endif; ?>

        <p><code>[sustainable_catalyst_data]</code> renders approved public records. <code>[catalyst_data_embed]</code> remains as a backward-compatible alias. <code>[catalyst_data_status]</code> renders compact status. <code>[catalyst_data_archive_search]</code> explores the locally cached Internet Archive catalog. <code>[catalyst_data_wayback]</code> renders locally cached Wayback history. <code>[catalyst_data_statistics]</code> renders cached World Bank or UN SDG observations. <code>[catalyst_data_us_public]</code> renders cached Census, BLS, BEA, EIA, or USGS observations. <code>[catalyst_data_earth]</code> renders cached NOAA/ERDDAP observations or USGS earthquakes. <code>[catalyst_data_ocean]</code> renders cached ERDDAP or IOOS dataset discovery. <code>[catalyst_data_space]</code> renders cached NASA/JPL space-weather, small-body, close-approach, or exoplanet data. <code>[catalyst_data_catalog]</code> searches the synchronized cross-provider dataset registry. <code>[catalyst_data_entity]</code> resolves cached canonical entities and identifiers. <code>[catalyst_data_graph]</code> federates cached cross-source observations through the connected data graph.</p>
    </div>
    <?php
}

function sustainable_catalyst_data_rest_error($error) {
    $status = 500;
    $data = $error->get_error_data();
    if (is_array($data) && isset($data['status'])) {
        $status = absint($data['status']);
    }
    return new WP_REST_Response(array('status' => 'error', 'code' => $error->get_error_code(), 'message' => $error->get_error_message()), $status);
}

function sustainable_catalyst_data_rest_health() {
    $payload = sustainable_catalyst_data_health();
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_records($request) {
    $limit = max(1, min(100, absint($request->get_param('limit') ?: 12)));
    $offset = max(0, absint($request->get_param('offset') ?: 0));
    $payload = sustainable_catalyst_data_fetch('/v1/records', array('limit' => $limit, 'offset' => $offset));
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_record($request) {
    $record_id = sanitize_text_field((string) $request['record_id']);
    $payload = sustainable_catalyst_data_fetch('/v1/records/' . rawurlencode($record_id));
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_archive_items($request) {
    $query = sanitize_text_field((string) ($request->get_param('query') ?: ''));
    $mediatype = sanitize_key((string) ($request->get_param('mediatype') ?: ''));
    $limit = max(1, min(100, absint($request->get_param('limit') ?: 25)));
    $offset = max(0, absint($request->get_param('offset') ?: 0));
    $params = array('limit' => $limit, 'offset' => $offset);
    if ($query !== '') { $params['query'] = $query; }
    if ($mediatype !== '') { $params['mediatype'] = $mediatype; }
    $payload = sustainable_catalyst_data_fetch('/v1/archive/items', $params);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_archive_item($request) {
    $identifier = sanitize_text_field((string) $request['identifier']);
    $payload = sustainable_catalyst_data_fetch('/v1/archive/items/' . rawurlencode($identifier));
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_wayback($request) {
    $url = esc_url_raw((string) ($request->get_param('url') ?: ''));
    if ($url === '') {
        return sustainable_catalyst_data_rest_error(new WP_Error('catalyst_data_invalid_url', 'A valid URL is required.', array('status' => 400)));
    }
    $limit = max(1, min(250, absint($request->get_param('limit') ?: 25)));
    $payload = sustainable_catalyst_data_fetch('/v1/wayback/captures', array('url' => $url, 'limit' => $limit));
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_statistics_status() {
    $payload = sustainable_catalyst_data_fetch('/v1/statistics/status', array(), 30);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_world_bank_observations($request) {
    $params = array(
        'limit' => max(1, min(500, absint($request->get_param('limit') ?: 100))),
        'offset' => max(0, absint($request->get_param('offset') ?: 0)),
    );
    foreach (array('country','indicator','start_period','end_period') as $key) {
        $value = sanitize_text_field((string) ($request->get_param($key) ?: ''));
        if ($value !== '') { $params[$key] = $value; }
    }
    $payload = sustainable_catalyst_data_fetch('/v1/statistics/world-bank/observations', $params);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_un_sdg_observations($request) {
    $params = array(
        'limit' => max(1, min(500, absint($request->get_param('limit') ?: 100))),
        'offset' => max(0, absint($request->get_param('offset') ?: 0)),
    );
    foreach (array('indicator','series','area_code','start_period','end_period') as $key) {
        $value = sanitize_text_field((string) ($request->get_param($key) ?: ''));
        if ($value !== '') { $params[$key] = $value; }
    }
    $payload = sustainable_catalyst_data_fetch('/v1/statistics/un-sdg/observations', $params);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_catalog_status() {
    $payload = sustainable_catalyst_data_fetch('/v1/catalog/status', array(), 30);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_catalog_datasets($request) {
    $params = array(
        'limit' => max(1, min(100, absint($request->get_param('limit') ?: 50))),
        'offset' => max(0, absint($request->get_param('offset') ?: 0)),
    );
    foreach (array('query','provider','resource_kind','freshness') as $key) {
        $value = sanitize_text_field((string) ($request->get_param($key) ?: ''));
        if ($value !== '') { $params[$key] = $value; }
    }
    $payload = sustainable_catalyst_data_fetch('/v1/catalog/datasets', $params);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_graph_status() {
    $payload = sustainable_catalyst_data_fetch('/v1/graph/status', array(), 30);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_rest_graph_federate($request) {
    $params = array('limit_per_source' => max(1, min(100, absint($request->get_param('limit_per_source') ?: 25))));
    foreach (array('entity_id','value','namespace') as $key) {
        $value = sanitize_text_field((string) ($request->get_param($key) ?: ''));
        if ($value !== '') { $params[$key] = $value; }
    }
    $payload = sustainable_catalyst_data_fetch('/v1/graph/federate', $params);
    return is_wp_error($payload) ? sustainable_catalyst_data_rest_error($payload) : rest_ensure_response($payload);
}

function sustainable_catalyst_data_register_rest_routes() {
    register_rest_route('sustainable-catalyst-data/v1', '/health', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_health', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/records', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_records', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/records/(?P<record_id>[A-Za-z0-9._:%-]+)', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_record', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/archive/items', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_archive_items', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/archive/items/(?P<identifier>[A-Za-z0-9._:%-]+)', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_archive_item', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/wayback/captures', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_wayback', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/statistics/status', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_statistics_status', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/statistics/world-bank/observations', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_world_bank_observations', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/statistics/un-sdg/observations', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_un_sdg_observations', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/catalog/status', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_catalog_status', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/catalog/datasets', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_catalog_datasets', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/graph/status', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_graph_status', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/graph/federate', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_graph_federate', 'permission_callback' => '__return_true'));
}
add_action('rest_api_init', 'sustainable_catalyst_data_register_rest_routes');

function sustainable_catalyst_data_register_assets() {
    $base = plugin_dir_url(__FILE__);
    wp_register_style('sustainable-catalyst-data', $base . 'assets/sustainable-catalyst-data.css', array(), SUSTAINABLE_CATALYST_DATA_VERSION);
    wp_register_script('sustainable-catalyst-data', $base . 'assets/sustainable-catalyst-data.js', array(), SUSTAINABLE_CATALYST_DATA_VERSION, true);
    wp_localize_script('sustainable-catalyst-data', 'SustainableCatalystData', array(
        'recordsUrl' => esc_url_raw(rest_url('sustainable-catalyst-data/v1/records')),
        'healthUrl' => esc_url_raw(rest_url('sustainable-catalyst-data/v1/health')),
        'version' => SUSTAINABLE_CATALYST_DATA_VERSION,
    ));
}
add_action('wp_enqueue_scripts', 'sustainable_catalyst_data_register_assets');

function sustainable_catalyst_data_shortcode($atts = array()) {
    $atts = shortcode_atts(array(
        'limit' => '12',
        'title' => 'Catalyst Data',
        'description' => 'Governed public data records with visible provenance, review status, and source context.',
    ), $atts, 'sustainable_catalyst_data');
    $limit = max(1, min(100, absint($atts['limit'])));
    wp_enqueue_style('sustainable-catalyst-data');
    wp_enqueue_script('sustainable-catalyst-data');
    ob_start(); ?>
    <section class="scd" data-sustainable-catalyst-data data-limit="<?php echo esc_attr($limit); ?>" aria-busy="true">
        <header class="scd__header"><p class="scd__eyebrow">Public Data Infrastructure</p><h2><?php echo esc_html($atts['title']); ?></h2><p><?php echo esc_html($atts['description']); ?></p></header>
        <div class="scd__toolbar"><p class="scd__status" role="status" aria-live="polite" data-scd-status>Connecting to Catalyst Data…</p><button type="button" class="scd__retry" data-scd-retry>Retry</button></div>
        <div class="scd__grid" role="list" data-scd-grid></div>
        <noscript><p class="scd__notice">JavaScript is required to load Catalyst Data records.</p></noscript>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('sustainable_catalyst_data', 'sustainable_catalyst_data_shortcode');
add_shortcode('catalyst_data_embed', 'sustainable_catalyst_data_shortcode');

function sustainable_catalyst_data_status_shortcode() {
    wp_enqueue_style('sustainable-catalyst-data');
    $health = sustainable_catalyst_data_health();
    if (is_wp_error($health)) {
        return '<div class="scd-status scd-status--attention"><strong>Catalyst Data:</strong> unavailable</div>';
    }
    $status = isset($health['status']) ? sanitize_text_field($health['status']) : 'unknown';
    $version = isset($health['version']) ? sanitize_text_field($health['version']) : 'unknown';
    return '<div class="scd-status"><strong>Catalyst Data:</strong> ' . esc_html($status) . ' · v' . esc_html($version) . '</div>';
}
add_shortcode('catalyst_data_status', 'sustainable_catalyst_data_status_shortcode');


function sustainable_catalyst_data_archive_shortcode($atts = array()) {
    $atts = shortcode_atts(array('query' => '', 'mediatype' => '', 'limit' => '12', 'title' => 'Internet Archive'), $atts, 'catalyst_data_archive_search');
    $limit = max(1, min(50, absint($atts['limit'])));
    $params = array('limit' => $limit, 'offset' => 0);
    if (trim((string) $atts['query']) !== '') { $params['query'] = sanitize_text_field($atts['query']); }
    if (trim((string) $atts['mediatype']) !== '') { $params['mediatype'] = sanitize_key($atts['mediatype']); }
    $payload = sustainable_catalyst_data_fetch('/v1/archive/items', $params);
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data Archive:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    $items = isset($payload['items']) && is_array($payload['items']) ? $payload['items'] : array();
    ob_start(); ?>
    <section class="scd scd--archive">
        <header class="scd__header"><p class="scd__eyebrow">Archival Evidence</p><h2><?php echo esc_html($atts['title']); ?></h2><p>Cataloged Internet Archive records retained by Catalyst Data with source identity and retrieval provenance.</p></header>
        <div class="scd__grid scd__grid--archive" role="list">
        <?php foreach ($items as $item) : $title = !empty($item['title']) ? $item['title'] : ($item['item_identifier'] ?? 'Archive item'); ?>
            <article class="scd__card" role="listitem">
                <p class="scd__card-eyebrow"><?php echo esc_html(!empty($item['mediatype']) ? $item['mediatype'] : 'Archive item'); ?></p>
                <h3><?php echo esc_html($title); ?></h3>
                <?php if (!empty($item['creator'])) : ?><p class="scd__indicator"><?php echo esc_html(is_array($item['creator']) ? implode(', ', array_map('sanitize_text_field', $item['creator'])) : $item['creator']); ?></p><?php endif; ?>
                <?php if (!empty($item['item_date'])) : ?><p class="scd__archive-date"><?php echo esc_html($item['item_date']); ?></p><?php endif; ?>
                <?php if (!empty($item['description'])) : ?><p class="scd__archive-description"><?php echo esc_html(wp_trim_words(wp_strip_all_tags((string) $item['description']), 30)); ?></p><?php endif; ?>
                <?php if (!empty($item['source_uri'])) : ?><a class="scd__source" href="<?php echo esc_url($item['source_uri']); ?>" target="_blank" rel="noopener noreferrer">View source ↗</a><?php endif; ?>
            </article>
        <?php endforeach; ?>
        </div>
        <?php if (!$items) : ?><p class="scd__notice">No matching Internet Archive items are cached in Catalyst Data yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_archive_search', 'sustainable_catalyst_data_archive_shortcode');

function sustainable_catalyst_data_wayback_shortcode($atts = array()) {
    $atts = shortcode_atts(array('url' => '', 'limit' => '20', 'title' => 'Wayback History'), $atts, 'catalyst_data_wayback');
    $url = esc_url_raw(trim((string) $atts['url']));
    if ($url === '') { return '<div class="scd-status scd-status--attention"><strong>Wayback:</strong> shortcode requires a URL.</div>'; }
    $limit = max(1, min(100, absint($atts['limit'])));
    $payload = sustainable_catalyst_data_fetch('/v1/wayback/captures', array('url' => $url, 'limit' => $limit));
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Wayback:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    $captures = isset($payload['captures']) && is_array($payload['captures']) ? $payload['captures'] : array();
    ob_start(); ?>
    <section class="scd scd--wayback">
        <header class="scd__header"><p class="scd__eyebrow">Temporal Evidence</p><h2><?php echo esc_html($atts['title']); ?></h2><p class="scd__wayback-target"><?php echo esc_html($url); ?></p></header>
        <ol class="scd__timeline">
        <?php foreach ($captures as $capture) : ?>
            <li class="scd__timeline-item">
                <time><?php echo esc_html(isset($capture['timestamp']) ? $capture['timestamp'] : 'Unknown timestamp'); ?></time>
                <span><?php echo esc_html(isset($capture['status_code']) && $capture['status_code'] ? 'HTTP ' . $capture['status_code'] : 'Archived capture'); ?></span>
                <?php if (!empty($capture['replay_url'])) : ?><a href="<?php echo esc_url($capture['replay_url']); ?>" target="_blank" rel="noopener noreferrer">Open capture ↗</a><?php endif; ?>
            </li>
        <?php endforeach; ?>
        </ol>
        <?php if (!$captures) : ?><p class="scd__notice">No cached Wayback captures are available for this URL yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_wayback', 'sustainable_catalyst_data_wayback_shortcode');

function sustainable_catalyst_data_statistics_shortcode($atts = array()) {
    $atts = shortcode_atts(array(
        'provider' => 'world-bank',
        'country' => '',
        'indicator' => '',
        'series' => '',
        'area_code' => '',
        'start_period' => '',
        'end_period' => '',
        'limit' => '20',
        'title' => 'Global Statistics',
    ), $atts, 'catalyst_data_statistics');
    $provider = sanitize_key($atts['provider']);
    if (!in_array($provider, array('world-bank','un-sdg'), true)) {
        return '<div class="scd-status scd-status--attention"><strong>Catalyst Data:</strong> provider must be world-bank or un-sdg.</div>';
    }
    $limit = max(1, min(100, absint($atts['limit'])));
    $params = array('limit' => $limit, 'offset' => 0);
    if ($provider === 'world-bank') {
        foreach (array('country','indicator','start_period','end_period') as $key) { if (trim((string) $atts[$key]) !== '') { $params[$key] = sanitize_text_field($atts[$key]); } }
        $payload = sustainable_catalyst_data_fetch('/v1/statistics/world-bank/observations', $params);
    } else {
        foreach (array('indicator','series','area_code','start_period','end_period') as $key) { if (trim((string) $atts[$key]) !== '') { $params[$key] = sanitize_text_field($atts[$key]); } }
        $payload = sustainable_catalyst_data_fetch('/v1/statistics/un-sdg/observations', $params);
    }
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data statistics:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    $items = isset($payload['observations']) && is_array($payload['observations']) ? $payload['observations'] : array();
    ob_start(); ?>
    <section class="scd scd--statistics">
        <header class="scd__header"><p class="scd__eyebrow">Governed Public Statistics</p><h2><?php echo esc_html($atts['title']); ?></h2><p><?php echo esc_html($provider === 'world-bank' ? 'Cached World Bank indicator observations with source and period context.' : 'Cached United Nations SDG indicator observations with M49 geography and disaggregation context.'); ?></p></header>
        <div class="scd__grid scd__grid--statistics" role="list">
        <?php foreach ($items as $item) :
            $label = $provider === 'world-bank' ? ($item['indicator_name'] ?? $item['indicator_code'] ?? 'Indicator') : ($item['series_description'] ?? $item['series_code'] ?? $item['indicator_code'] ?? 'SDG series');
            $area = $provider === 'world-bank' ? ($item['country_name'] ?? $item['country_code'] ?? '') : ($item['geo_area_name'] ?? $item['geo_area_code'] ?? '');
            $period = $provider === 'world-bank' ? ($item['period'] ?? '') : ($item['time_period'] ?? '');
            $value = isset($item['value_numeric']) && $item['value_numeric'] !== null ? $item['value_numeric'] : ($item['value_text'] ?? '—');
            $unit = $provider === 'world-bank' ? ($item['unit'] ?? '') : ($item['units'] ?? ''); ?>
            <article class="scd__card" role="listitem">
                <p class="scd__card-eyebrow"><?php echo esc_html(($area !== '' ? $area . ' · ' : '') . $period); ?></p>
                <h3><?php echo esc_html($label); ?></h3>
                <p class="scd__stat-value"><?php echo esc_html((string) $value); ?><?php echo $unit !== '' ? ' <span>' . esc_html($unit) . '</span>' : ''; ?></p>
                <?php if (!empty($item['source_uri'])) : ?><a class="scd__source" href="<?php echo esc_url($item['source_uri']); ?>" target="_blank" rel="noopener noreferrer">Source request ↗</a><?php endif; ?>
            </article>
        <?php endforeach; ?>
        </div>
        <?php if (!$items) : ?><p class="scd__notice">No matching cached statistics are available yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_statistics', 'sustainable_catalyst_data_statistics_shortcode');


function sustainable_catalyst_data_us_public_shortcode($atts = array()) {
    $atts = shortcode_atts(array(
        'provider' => '', 'metric' => '', 'geography' => '', 'start_period' => '', 'end_period' => '',
        'limit' => '20', 'title' => 'U.S. Public Data',
    ), $atts, 'catalyst_data_us_public');
    $provider = sanitize_key($atts['provider']);
    if ($provider !== '' && !in_array($provider, array('census','bls','bea','eia','usgs'), true)) {
        return '<div class="scd-status scd-status--attention"><strong>Catalyst Data:</strong> provider must be census, bls, bea, eia, or usgs.</div>';
    }
    $params = array('limit' => max(1, min(100, absint($atts['limit']))), 'offset' => 0);
    foreach (array('provider','metric','geography','start_period','end_period') as $key) {
        if (trim((string) $atts[$key]) !== '') { $params[$key] = sanitize_text_field($atts[$key]); }
    }
    $payload = sustainable_catalyst_data_fetch('/v1/us-public/observations', $params);
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data U.S. public data:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    $items = isset($payload['observations']) && is_array($payload['observations']) ? $payload['observations'] : array();
    ob_start(); ?>
    <section class="scd scd--statistics scd--us-public">
        <header class="scd__header"><p class="scd__eyebrow">Governed Federal Data</p><h2><?php echo esc_html($atts['title']); ?></h2><p>Cached U.S. public-data observations with source-native identifiers, period context, and provenance.</p></header>
        <div class="scd__grid scd__grid--statistics" role="list">
        <?php foreach ($items as $item) :
            $label = !empty($item['metric_name']) ? $item['metric_name'] : (!empty($item['metric_code']) ? $item['metric_code'] : 'Observation');
            $area = !empty($item['geography_name']) ? $item['geography_name'] : (!empty($item['geography_id']) ? $item['geography_id'] : '');
            $period = !empty($item['period']) ? $item['period'] : '';
            $value = isset($item['value_numeric']) && $item['value_numeric'] !== null ? $item['value_numeric'] : (isset($item['value_text']) ? $item['value_text'] : '—');
            $unit = !empty($item['unit']) ? $item['unit'] : ''; ?>
            <article class="scd__card" role="listitem">
                <p class="scd__card-eyebrow"><?php echo esc_html(strtoupper((string) ($item['provider'] ?? 'data')) . (($area !== '' || $period !== '') ? ' · ' . trim($area . ' ' . $period) : '')); ?></p>
                <h3><?php echo esc_html($label); ?></h3>
                <p class="scd__stat-value"><?php echo esc_html((string) $value); ?><?php echo $unit !== '' ? ' <span>' . esc_html($unit) . '</span>' : ''; ?></p>
                <?php if (!empty($item['source_uri'])) : ?><a class="scd__source" href="<?php echo esc_url($item['source_uri']); ?>" target="_blank" rel="noopener noreferrer">Source request ↗</a><?php endif; ?>
            </article>
        <?php endforeach; ?>
        </div>
        <?php if (!$items) : ?><p class="scd__notice">No matching cached U.S. public-data observations are available yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_us_public', 'sustainable_catalyst_data_us_public_shortcode');



function sustainable_catalyst_data_earth_shortcode($atts = array()) {
    $atts = shortcode_atts(array(
        'mode' => 'observations', 'provider' => '', 'dataset_id' => '', 'metric' => '', 'station_id' => '',
        'min_magnitude' => '', 'limit' => '20', 'title' => 'Earth, Climate & Ocean Data',
    ), $atts, 'catalyst_data_earth');
    $mode = sanitize_key($atts['mode']);
    $limit = max(1, min(100, absint($atts['limit'])));
    if ($mode === 'earthquakes') {
        $params = array('limit' => $limit, 'offset' => 0);
        if (trim((string) $atts['min_magnitude']) !== '') { $params['min_magnitude'] = (float) $atts['min_magnitude']; }
        $payload = sustainable_catalyst_data_fetch('/v1/earth/earthquakes', $params);
        $items = !is_wp_error($payload) && isset($payload['events']) && is_array($payload['events']) ? $payload['events'] : array();
    } else {
        $params = array('limit' => $limit, 'offset' => 0);
        foreach (array('provider','dataset_id','metric','station_id') as $key) { if (trim((string) $atts[$key]) !== '') { $params[$key] = sanitize_text_field($atts[$key]); } }
        $payload = sustainable_catalyst_data_fetch('/v1/earth/observations', $params);
        $items = !is_wp_error($payload) && isset($payload['observations']) && is_array($payload['observations']) ? $payload['observations'] : array();
    }
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data earth network:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    ob_start(); ?>
    <section class="scd scd--statistics scd--earth">
        <header class="scd__header"><p class="scd__eyebrow">Environmental Evidence</p><h2><?php echo esc_html($atts['title']); ?></h2><p>Cached environmental observations and hazard events with source-native identifiers and provenance.</p></header>
        <div class="scd__grid scd__grid--statistics" role="list">
        <?php foreach ($items as $item) :
            if ($mode === 'earthquakes') {
                $label = !empty($item['place']) ? $item['place'] : ($item['event_id'] ?? 'Earthquake');
                $eyebrow = trim(($item['event_time'] ?? '') . (!empty($item['magnitude']) ? ' · M ' . $item['magnitude'] : ''));
                $value = !empty($item['depth_km']) ? $item['depth_km'] . ' km depth' : 'USGS event';
            } else {
                $label = !empty($item['metric_code']) ? $item['metric_code'] : 'Observation';
                $eyebrow = strtoupper((string) ($item['provider'] ?? 'data')) . (!empty($item['period']) ? ' · ' . $item['period'] : '');
                $value = isset($item['value_numeric']) && $item['value_numeric'] !== null ? $item['value_numeric'] : ($item['value_text'] ?? '—');
                if (!empty($item['unit'])) { $value .= ' ' . $item['unit']; }
            } ?>
            <article class="scd__card" role="listitem"><p class="scd__card-eyebrow"><?php echo esc_html($eyebrow); ?></p><h3><?php echo esc_html($label); ?></h3><p class="scd__stat-value"><?php echo esc_html((string) $value); ?></p><?php if (!empty($item['source_uri'])) : ?><a class="scd__source" href="<?php echo esc_url($item['source_uri']); ?>" target="_blank" rel="noopener noreferrer">Source request ↗</a><?php endif; ?></article>
        <?php endforeach; ?>
        </div>
        <?php if (!$items) : ?><p class="scd__notice">No matching cached environmental data are available yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_earth', 'sustainable_catalyst_data_earth_shortcode');

function sustainable_catalyst_data_ocean_shortcode($atts = array()) {
    $atts = shortcode_atts(array('source' => 'erddap', 'query' => '', 'limit' => '20', 'title' => 'Ocean Data Catalog'), $atts, 'catalyst_data_ocean');
    $source = sanitize_key($atts['source']);
    if (!in_array($source, array('erddap','ioos'), true)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data ocean:</strong> source must be erddap or ioos.</div>'; }
    $params = array('limit' => max(1, min(100, absint($atts['limit']))), 'offset' => 0);
    if (trim((string) $atts['query']) !== '') { $params['query'] = sanitize_text_field($atts['query']); }
    $payload = sustainable_catalyst_data_fetch($source === 'erddap' ? '/v1/ocean/erddap-datasets' : '/v1/ocean/ioos-datasets', $params);
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data ocean:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    $items = isset($payload['datasets']) && is_array($payload['datasets']) ? $payload['datasets'] : array();
    ob_start(); ?>
    <section class="scd scd--archive scd--ocean"><header class="scd__header"><p class="scd__eyebrow">Ocean & Coastal Data</p><h2><?php echo esc_html($atts['title']); ?></h2><p>Cached dataset discovery from ERDDAP and the U.S. IOOS data network.</p></header><div class="scd__grid scd__grid--archive" role="list">
    <?php foreach ($items as $item) : $label = !empty($item['title']) ? $item['title'] : ($item['dataset_id'] ?? $item['name'] ?? 'Dataset'); ?>
        <article class="scd__card" role="listitem"><p class="scd__card-eyebrow"><?php echo esc_html(strtoupper($source) . (!empty($item['institution']) ? ' · ' . $item['institution'] : (!empty($item['organization']) ? ' · ' . $item['organization'] : ''))); ?></p><h3><?php echo esc_html($label); ?></h3><?php if (!empty($item['notes'])) : ?><p><?php echo esc_html(wp_trim_words(wp_strip_all_tags((string) $item['notes']), 28)); ?></p><?php endif; ?><?php if (!empty($item['source_uri'])) : ?><a class="scd__source" href="<?php echo esc_url($item['source_uri']); ?>" target="_blank" rel="noopener noreferrer">Catalog source ↗</a><?php endif; ?></article>
    <?php endforeach; ?></div><?php if (!$items) : ?><p class="scd__notice">No matching cached ocean datasets are available yet.</p><?php endif; ?></section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_ocean', 'sustainable_catalyst_data_ocean_shortcode');

function sustainable_catalyst_data_space_shortcode($atts = array()) {
    $atts = shortcode_atts(array(
        'mode' => 'space-weather',
        'query' => '',
        'event_type' => '',
        'body' => '',
        'orbit_class' => '',
        'discovery_method' => '',
        'limit' => '20',
        'title' => 'Space & Scientific Data',
    ), $atts, 'catalyst_data_space');
    $mode = sanitize_key((string) $atts['mode']);
    $allowed = array('space-weather','small-bodies','close-approaches','exoplanets');
    if (!in_array($mode, $allowed, true)) {
        return '<div class="scd-status scd-status--attention"><strong>Catalyst Data space:</strong> invalid mode.</div>';
    }
    $limit = max(1, min(100, absint($atts['limit'])));
    $params = array('limit' => $limit);
    $path = '/v1/space/weather-events';
    if ($mode === 'space-weather') {
        $event_type = sanitize_text_field((string) $atts['event_type']);
        if ($event_type !== '') { $params['event_type'] = $event_type; }
    } elseif ($mode === 'small-bodies') {
        $path = '/v1/space/small-bodies';
        $query = sanitize_text_field((string) $atts['query']);
        $orbit_class = sanitize_text_field((string) $atts['orbit_class']);
        if ($query !== '') { $params['query'] = $query; }
        if ($orbit_class !== '') { $params['orbit_class'] = $orbit_class; }
    } elseif ($mode === 'close-approaches') {
        $path = '/v1/space/close-approaches';
        $body = sanitize_text_field((string) $atts['body']);
        if ($body !== '') { $params['body'] = $body; }
    } else {
        $path = '/v1/space/exoplanets';
        $query = sanitize_text_field((string) $atts['query']);
        $method = sanitize_text_field((string) $atts['discovery_method']);
        if ($query !== '') { $params['query'] = $query; }
        if ($method !== '') { $params['discovery_method'] = $method; }
    }
    $payload = sustainable_catalyst_data_fetch($path, $params);
    if (is_wp_error($payload)) {
        return '<div class="scd-status scd-status--attention"><strong>Catalyst Data space:</strong> ' . esc_html($payload->get_error_message()) . '</div>';
    }
    if ($mode === 'space-weather') { $items = isset($payload['events']) && is_array($payload['events']) ? $payload['events'] : array(); }
    elseif ($mode === 'small-bodies') { $items = isset($payload['objects']) && is_array($payload['objects']) ? $payload['objects'] : array(); }
    elseif ($mode === 'close-approaches') { $items = isset($payload['approaches']) && is_array($payload['approaches']) ? $payload['approaches'] : array(); }
    else { $items = isset($payload['planets']) && is_array($payload['planets']) ? $payload['planets'] : array(); }
    wp_enqueue_style('sustainable-catalyst-data');
    ob_start(); ?>
    <section class="scd scd--statistics scd--space">
        <header class="scd__header"><p class="scd__eyebrow">Space &amp; Scientific Data</p><h2><?php echo esc_html($atts['title']); ?></h2><p>Cached NASA and JPL records served through Catalyst Data with source identity and acquisition boundaries preserved.</p></header>
        <div class="scd__grid scd__grid--statistics" role="list">
        <?php foreach ($items as $item) :
            if ($mode === 'space-weather') { $heading = isset($item['event_type']) ? $item['event_type'] : 'Space weather'; $meta = isset($item['event_time']) ? $item['event_time'] : ''; $value = isset($item['title']) ? $item['title'] : ''; }
            elseif ($mode === 'small-bodies') { $heading = !empty($item['name']) ? $item['name'] : (!empty($item['full_name']) ? $item['full_name'] : $item['designation']); $meta = trim((!empty($item['orbit_class']) ? $item['orbit_class'] : '') . (!empty($item['is_neo']) ? ' · NEO' : '') . (!empty($item['is_pha']) ? ' · PHA' : '')); $value = isset($item['diameter_km']) && $item['diameter_km'] !== null ? $item['diameter_km'] . ' km' : ''; }
            elseif ($mode === 'close-approaches') { $heading = !empty($item['full_name']) ? trim($item['full_name']) : $item['designation']; $meta = trim((isset($item['close_approach_time']) ? $item['close_approach_time'] : '') . ' · ' . (isset($item['body']) ? $item['body'] : '')); $value = isset($item['distance_au']) && $item['distance_au'] !== null ? $item['distance_au'] . ' au' : ''; }
            else { $heading = isset($item['planet_name']) ? $item['planet_name'] : 'Exoplanet'; $meta = trim((isset($item['host_name']) ? $item['host_name'] : '') . (isset($item['discovery_method']) && $item['discovery_method'] ? ' · ' . $item['discovery_method'] : '')); $value = isset($item['radius_earth']) && $item['radius_earth'] !== null ? $item['radius_earth'] . ' R⊕' : ''; }
        ?>
            <article class="scd-card" role="listitem"><p class="scd-card__meta"><?php echo esc_html($meta); ?></p><h3><?php echo esc_html($heading); ?></h3><?php if ($value !== '') : ?><p class="scd-card__value"><?php echo esc_html($value); ?></p><?php endif; ?></article>
        <?php endforeach; ?>
        </div>
        <?php if (!$items) : ?><p class="scd__notice">No matching cached space-science records are available yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_space', 'sustainable_catalyst_data_space_shortcode');


function sustainable_catalyst_data_catalog_shortcode($atts = array()) {
    $atts = shortcode_atts(array(
        'query' => '',
        'provider' => '',
        'resource_kind' => '',
        'freshness' => '',
        'limit' => '18',
        'title' => 'Explore Catalyst Data',
    ), $atts, 'catalyst_data_catalog');
    $params = array('limit' => max(1, min(100, absint($atts['limit']))), 'offset' => 0);
    foreach (array('query','provider','resource_kind','freshness') as $key) {
        $value = sanitize_text_field((string) $atts[$key]);
        if ($value !== '') { $params[$key] = $value; }
    }
    $payload = sustainable_catalyst_data_fetch('/v1/catalog/datasets', $params);
    wp_enqueue_style('sustainable-catalyst-data');
    if (is_wp_error($payload)) {
        return '<div class="scd-status scd-status--attention"><strong>Catalyst Data catalog:</strong> ' . esc_html($payload->get_error_message()) . '</div>';
    }
    $items = isset($payload['datasets']) && is_array($payload['datasets']) ? $payload['datasets'] : array();
    ob_start(); ?>
    <section class="scd scd--archive scd--catalog">
        <header class="scd__header"><p class="scd__eyebrow">Dataset Registry</p><h2><?php echo esc_html($atts['title']); ?></h2><p>Cross-provider discovery over datasets already governed and cached by Catalyst Data. Catalog views do not trigger upstream acquisition.</p></header>
        <div class="scd__grid scd__grid--archive" role="list">
        <?php foreach ($items as $item) : ?>
            <article class="scd__card" role="listitem">
                <p class="scd__card-eyebrow"><?php echo esc_html(strtoupper(isset($item['provider']) ? $item['provider'] : 'DATA') . (isset($item['resource_kind']) ? ' · ' . $item['resource_kind'] : '')); ?></p>
                <h3><?php echo esc_html(isset($item['title']) ? $item['title'] : 'Dataset'); ?></h3>
                <?php if (!empty($item['description'])) : ?><p><?php echo esc_html(wp_trim_words(wp_strip_all_tags((string) $item['description']), 30)); ?></p><?php endif; ?>
                <p class="scd__indicator"><?php echo esc_html((isset($item['record_count']) ? $item['record_count'] : '0') . ' records' . (isset($item['freshness_status']) ? ' · ' . $item['freshness_status'] : '')); ?></p>
                <?php if (!empty($item['geographic_coverage'])) : ?><p class="scd__archive-date"><?php echo esc_html($item['geographic_coverage']); ?></p><?php endif; ?>
                <?php if (!empty($item['source_uri'])) : ?><a class="scd__source" href="<?php echo esc_url($item['source_uri']); ?>" target="_blank" rel="noopener noreferrer">Source ↗</a><?php endif; ?>
            </article>
        <?php endforeach; ?>
        </div>
        <?php if (!$items) : ?><p class="scd__notice">No matching synchronized dataset catalog entries are available yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_catalog', 'sustainable_catalyst_data_catalog_shortcode');



function sustainable_catalyst_data_entity_shortcode($atts = array()) {
    $atts = shortcode_atts(array('value' => '', 'namespace' => '', 'entity_type' => '', 'title' => 'Entity resolution'), $atts, 'catalyst_data_entity');
    if (!$atts['value']) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data entity:</strong> value is required.</div>'; }
    $params = array('value' => $atts['value']);
    if ($atts['namespace']) { $params['namespace'] = $atts['namespace']; }
    if ($atts['entity_type']) { $params['entity_type'] = $atts['entity_type']; }
    $payload = sustainable_catalyst_data_fetch('/v1/entities/resolve', $params, 30);
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data entity:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    ob_start(); ?>
    <section class="scd scd--entity">
      <h3><?php echo esc_html($atts['title']); ?></h3>
      <p><strong><?php echo esc_html(isset($payload['status']) ? $payload['status'] : 'unknown'); ?></strong> — <?php echo esc_html($atts['value']); ?></p>
      <?php if (isset($payload['entity']) && is_array($payload['entity'])) : ?>
        <p><?php echo esc_html($payload['entity']['canonical_name']); ?> <code><?php echo esc_html($payload['entity']['entity_id']); ?></code></p>
      <?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_entity', 'sustainable_catalyst_data_entity_shortcode');


function sustainable_catalyst_data_graph_shortcode($atts = array()) {
    $atts = shortcode_atts(array('value' => '', 'namespace' => '', 'entity_id' => '', 'limit' => '8', 'title' => 'Connected data'), $atts, 'catalyst_data_graph');
    $params = array('limit_per_source' => max(1, min(25, absint($atts['limit']))));
    if ($atts['entity_id']) { $params['entity_id'] = $atts['entity_id']; }
    elseif ($atts['value']) { $params['value'] = $atts['value']; if ($atts['namespace']) { $params['namespace'] = $atts['namespace']; } }
    else { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data graph:</strong> value or entity_id is required.</div>'; }
    $payload = sustainable_catalyst_data_fetch('/v1/graph/federate', $params, 30);
    if (is_wp_error($payload)) { return '<div class="scd-status scd-status--attention"><strong>Catalyst Data graph:</strong> ' . esc_html($payload->get_error_message()) . '</div>'; }
    ob_start(); ?>
    <section class="scd scd--graph">
      <header class="scd__header"><p class="scd__eyebrow">Connected Data Graph</p><h2><?php echo esc_html($atts['title']); ?></h2></header>
      <?php if (!empty($payload['entity']['canonical_name'])) : ?><p><strong><?php echo esc_html($payload['entity']['canonical_name']); ?></strong> · <?php echo esc_html(isset($payload['source_count']) ? $payload['source_count'] : 0); ?> connected source families</p><?php endif; ?>
      <div class="scd__grid">
      <?php foreach ((isset($payload['sources']) && is_array($payload['sources']) ? $payload['sources'] : array()) as $source) : ?>
        <article class="scd__card">
          <p class="scd__card-eyebrow"><?php echo esc_html(strtoupper(isset($source['provider']) ? $source['provider'] : 'SOURCE')); ?></p>
          <h3><?php echo esc_html(isset($source['total']) ? $source['total'] . ' cached observations' : 'Cached observations'); ?></h3>
          <?php $observations = isset($source['observations']) && is_array($source['observations']) ? array_slice($source['observations'], 0, 3) : array(); ?>
          <?php foreach ($observations as $observation) : ?>
            <p class="scd__archive-date"><?php echo esc_html(wp_trim_words(wp_strip_all_tags(wp_json_encode($observation)), 18)); ?></p>
          <?php endforeach; ?>
        </article>
      <?php endforeach; ?>
      </div>
      <?php if (empty($payload['sources'])) : ?><p class="scd__notice">No connected cached observations are available for this entity yet.</p><?php endif; ?>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('catalyst_data_graph', 'sustainable_catalyst_data_graph_shortcode');
