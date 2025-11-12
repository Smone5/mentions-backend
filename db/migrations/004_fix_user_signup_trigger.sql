-- Migration 004: Fix User Signup Trigger
-- Description: Fixes conflicts and ensures signup trigger works properly
-- Date: 2024-11-07

-- First, check if company_id column exists and modify if needed
DO $$ 
BEGIN
    -- If company_id exists as NOT NULL, make it nullable for signup flow
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_profiles' 
        AND column_name = 'company_id' 
        AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE user_profiles ALTER COLUMN company_id DROP NOT NULL;
    END IF;
END $$;

-- Add missing columns if they don't exist
ALTER TABLE user_profiles 
ADD COLUMN IF NOT EXISTS full_name TEXT,
ADD COLUMN IF NOT EXISTS phone_number TEXT,
ADD COLUMN IF NOT EXISTS birthdate DATE,
ADD COLUMN IF NOT EXISTS sms_consent BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS sms_opt_out_at TIMESTAMPTZ;

-- Add owner_id to companies if it doesn't exist
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

-- Create indices
CREATE INDEX IF NOT EXISTS idx_user_profiles_phone_number 
ON user_profiles(phone_number) WHERE phone_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_user_profiles_sms_consent 
ON user_profiles(sms_consent) 
WHERE sms_consent = TRUE AND sms_opt_out_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_companies_owner_id 
ON companies(owner_id);

-- Drop existing trigger and function
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
DROP FUNCTION IF EXISTS handle_new_user_signup() CASCADE;

-- Create improved signup handler function
CREATE OR REPLACE FUNCTION handle_new_user_signup()
RETURNS TRIGGER AS $$
DECLARE
    new_company_id UUID;
    birthdate_val DATE;
    company_name_val TEXT;
BEGIN
    -- Log for debugging (will show in Supabase logs)
    RAISE LOG 'handle_new_user_signup triggered for user %', NEW.id;
    
    -- Handle birthdate conversion safely
    IF NEW.raw_user_meta_data ? 'birthdate' AND 
       NEW.raw_user_meta_data->>'birthdate' IS NOT NULL AND 
       NEW.raw_user_meta_data->>'birthdate' != '' THEN
        BEGIN
            birthdate_val := (NEW.raw_user_meta_data->>'birthdate')::DATE;
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'Failed to parse birthdate: %', NEW.raw_user_meta_data->>'birthdate';
            birthdate_val := NULL;
        END;
    ELSE
        birthdate_val := NULL;
    END IF;
    
    -- Get company name or use default from email
    company_name_val := COALESCE(
        NULLIF(TRIM(NEW.raw_user_meta_data->>'company_name'), ''),
        NULLIF(TRIM(NEW.raw_user_meta_data->>'full_name'), ''),
        SPLIT_PART(NEW.email, '@', 1) || '''s Company'
    );
    
    -- Create company FIRST with NULL owner_id (to break circular dependency)
    BEGIN
        INSERT INTO companies (name, owner_id, created_at, updated_at)
        VALUES (
            company_name_val,
            NULL,  -- Will be set after user_profile is created
            NOW(),
            NOW()
        )
        RETURNING id INTO new_company_id;
        
        RAISE LOG 'Created company % for user %', new_company_id, NEW.id;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'Failed to create company: %', SQLERRM;
        RAISE;
    END;
    
    -- Insert user profile with company_id
    BEGIN
        INSERT INTO user_profiles (
            id, 
            company_id,
            role,
            full_name, 
            phone_number, 
            birthdate, 
            sms_consent,
            created_at,
            updated_at
        )
        VALUES (
            NEW.id,
            new_company_id,
            'owner',  -- First user is the owner
            COALESCE(NULLIF(TRIM(NEW.raw_user_meta_data->>'full_name'), ''), SPLIT_PART(NEW.email, '@', 1)),
            NULLIF(TRIM(NEW.raw_user_meta_data->>'phone_number'), ''),
            birthdate_val,
            COALESCE((NEW.raw_user_meta_data->>'sms_consent')::BOOLEAN, FALSE),
            NOW(),
            NOW()
        );
        
        RAISE LOG 'Created user_profile for user %', NEW.id;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'Failed to create user_profile: %', SQLERRM;
        -- Cleanup: Delete the company we just created
        DELETE FROM companies WHERE id = new_company_id;
        RAISE;
    END;
    
    -- Update company to set owner_id (breaking the circular dependency)
    BEGIN
        UPDATE companies
        SET owner_id = NEW.id, updated_at = NOW()
        WHERE id = new_company_id;
        
        RAISE LOG 'Set company owner for company %', new_company_id;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'Failed to set company owner: %', SQLERRM;
        RAISE;
    END;
    
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    -- Log the full error for debugging
    RAISE WARNING 'handle_new_user_signup failed: %', SQLERRM;
    RAISE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create trigger for new user signups
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user_signup();

-- Update RLS policies (drop and recreate to avoid conflicts)
DROP POLICY IF EXISTS "Users can view own profile" ON user_profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON user_profiles;
DROP POLICY IF EXISTS "Users can view own company" ON companies;
DROP POLICY IF EXISTS "Owners can update company" ON companies;
DROP POLICY IF EXISTS "Service role can insert profiles" ON user_profiles;

-- Enable RLS
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;

-- Users can read their own profile
CREATE POLICY "Users can view own profile"
    ON user_profiles FOR SELECT
    USING (auth.uid() = id);

-- Users can update their own profile
CREATE POLICY "Users can update own profile"
    ON user_profiles FOR UPDATE
    USING (auth.uid() = id);

-- Users can read companies they're associated with
CREATE POLICY "Users can view own company"
    ON companies FOR SELECT
    USING (
        owner_id = auth.uid() OR
        id IN (SELECT company_id FROM user_profiles WHERE id = auth.uid())
    );

-- Company owners can update their company
CREATE POLICY "Owners can update company"
    ON companies FOR UPDATE
    USING (owner_id = auth.uid());

-- Allow authenticated users to insert during trigger execution
CREATE POLICY "Service role can insert profiles"
    ON user_profiles FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Service role can insert companies"
    ON companies FOR INSERT
    WITH CHECK (true);

-- Grant necessary permissions
GRANT USAGE ON SCHEMA public TO authenticated, anon;
GRANT ALL ON user_profiles TO authenticated;
GRANT ALL ON companies TO authenticated;

-- Comments for documentation
COMMENT ON FUNCTION handle_new_user_signup() IS 'Automatically creates company and user_profile when a new user signs up via Supabase Auth';
COMMENT ON TRIGGER on_auth_user_created ON auth.users IS 'Trigger that runs after a new user is created in auth.users';

