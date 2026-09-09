export type TeamAvatar = { value: string; label: string; category: string };

const entries: Record<string, string[]> = {
  Teams: ['groups', 'group', 'diversity_1', 'diversity_2', 'diversity_3', 'partner_exchange', 'handshake', 'hub', 'account_tree', 'social_leaderboard', 'trophy', 'workspace_premium'],
  Strength: ['shield', 'swords', 'military_tech', 'security', 'bolt', 'local_fire_department', 'sports_martial_arts', 'exercise', 'fitness_center', 'mountain_flag', 'castle', 'fort'],
  Health: ['health_and_safety', 'medical_services', 'cardiology', 'ecg_heart', 'stethoscope', 'healing', 'emergency', 'ambulance', 'pill', 'vaccines', 'vital_signs', 'heart_check'],
  Nature: ['forest', 'park', 'eco', 'nature', 'potted_plant', 'water_drop', 'waves', 'air', 'sunny', 'dark_mode', 'landscape', 'volcano'],
  Animals: ['pets', 'raven', 'owl', 'flutter_dash', 'cruelty_free', 'pest_control', 'bug_report', 'egg', 'nest_eco_leaf', 'sound_detection_dog_barking', 'hive', 'coronavirus'],
  Space: ['rocket_launch', 'rocket', 'planet', 'public', 'language', 'explore', 'travel_explore', 'orbit', 'satellite_alt', 'star', 'stars', 'flare'],
  Technology: ['memory', 'developer_board', 'terminal', 'code', 'data_object', 'database', 'dns', 'lan', 'network_node', 'smart_toy', 'robot_2', 'precision_manufacturing'],
  Ideas: ['lightbulb', 'psychology', 'neurology', 'school', 'science', 'biotech', 'experiment', 'genetics', 'strategy', 'target', 'track_changes', 'query_stats'],
  Objects: ['diamond', 'key', 'anchor', 'flag', 'crown', 'token', 'verified', 'grade', 'auto_awesome', 'magic_button', 'palette', 'draw'],
  Motion: ['speed', 'flight', 'sailing', 'directions_run', 'sports_score', 'arrow_outward', 'north_east', 'trending_up', 'moving', 'cycle', 'electric_bolt', 'offline_bolt'],
};

const title = (value: string) => value.split('_').map((word) => `${word[0].toUpperCase()}${word.slice(1)}`).join(' ');

export const TEAM_AVATARS: TeamAvatar[] = Object.entries(entries).flatMap(([category, values]) =>
  values.map((value) => ({ value, label: title(value), category })),
);

export const DEFAULT_TEAM_AVATAR = 'groups';
