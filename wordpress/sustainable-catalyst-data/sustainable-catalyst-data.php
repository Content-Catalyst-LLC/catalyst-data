<?php
/**
 * Plugin Name: Sustainable Catalyst Data
 * Description: Governed WordPress integration for Catalyst Data public records and archival intelligence, with health diagnostics, cached Archive.org/Wayback discovery, and provenance-aware embeds.
 * Version: 2.3.0
 * Author: Content Catalyst LLC
 * License: MIT
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if (!defined('ABSPATH')) {
    exit;
}

define('SUSTAINABLE_CATALYST_DATA_VERSION', '2.3.0');
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
        <h2>Shortcodes</h2>
        <p><code>[sustainable_catalyst_data]</code> renders approved public records. <code>[catalyst_data_embed]</code> remains as a backward-compatible alias. <code>[catalyst_data_status]</code> renders compact status. <code>[catalyst_data_archive_search]</code> explores the locally cached Internet Archive catalog. <code>[catalyst_data_wayback]</code> renders locally cached Wayback history for a URL.</p>
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

function sustainable_catalyst_data_register_rest_routes() {
    register_rest_route('sustainable-catalyst-data/v1', '/health', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_health', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/records', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_records', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/records/(?P<record_id>[A-Za-z0-9._:%-]+)', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_record', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/archive/items', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_archive_items', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/archive/items/(?P<identifier>[A-Za-z0-9._:%-]+)', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_archive_item', 'permission_callback' => '__return_true'));
    register_rest_route('sustainable-catalyst-data/v1', '/wayback/captures', array('methods' => WP_REST_Server::READABLE, 'callback' => 'sustainable_catalyst_data_rest_wayback', 'permission_callback' => '__return_true'));
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
