CREATE TABLE `favorites` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`brand` text,
	`barcode` text,
	`serving_g` real,
	`calories` real,
	`protein_g` real,
	`carbs_g` real,
	`fat_g` real,
	`fiber_g` real,
	`sugar_g` real,
	`sodium_mg` real,
	`use_count` integer DEFAULT 0 NOT NULL,
	`last_used_at` text DEFAULT CURRENT_TIMESTAMP
);
--> statement-breakpoint
CREATE TABLE `meals` (
	`client_id` text PRIMARY KEY NOT NULL,
	`name` text,
	`brand` text,
	`barcode` text,
	`serving_g` real,
	`calories` real,
	`protein_g` real,
	`carbs_g` real,
	`fat_g` real,
	`fiber_g` real,
	`sugar_g` real,
	`sodium_mg` real,
	`meal_type` text,
	`eaten_at` text NOT NULL,
	`source` text DEFAULT 'manual' NOT NULL,
	`model_confidence` real,
	`user_edited` integer DEFAULT false NOT NULL,
	`deleted` integer DEFAULT false NOT NULL,
	`updated_at` text NOT NULL,
	`dirty` integer DEFAULT true NOT NULL
);
--> statement-breakpoint
CREATE INDEX `meals_eaten_at_idx` ON `meals` (`eaten_at`);--> statement-breakpoint
CREATE INDEX `meals_dirty_idx` ON `meals` (`dirty`);--> statement-breakpoint
CREATE TABLE `sync_state` (
	`id` integer PRIMARY KEY DEFAULT 1 NOT NULL,
	`cursor` text,
	`last_synced_at` text
);
