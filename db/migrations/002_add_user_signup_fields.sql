-- Migration: Add user signup fields
-- Description: Adds full_name, phone_number, birthdate, and SMS consent fields to user_profiles
-- Date: 2024

-- Add new columns to user_profiles if they don't exist
ALTER TABLE user_profiles 
ADD COLUMN IF NOT EXISTS full_name TEXT,
ADD COLUMN IF NOT EXISTS phone_number TEXT,
ADD COLUMN IF NOT EXISTS birthdate DATE,
ADD COLUMN IF NOT EXISTS sms_consent BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS sms_opt_out_at TIMESTAMPTZ;

-- Add company relationship to user_profiles
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES companies(id) ON DELETE SET NULL;

-- Create index for phone number lookups
CREATE INDEX IF NOT EXISTS idx_user_profiles_phone_number ON user_profiles(phone_number) WHERE phone_number IS NOT NULL;

-- Create index for SMS consent users
CREATE INDEX IF NOT EXISTS idx_user_profiles_sms_consent ON user_profiles(sms_consent) WHERE sms_consent = TRUE AND sms_opt_out_at IS NULL;

-- Create function to handle user signup with extended profile
CREATE OR REPLACE FUNCTION handle_new_user_signup()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO user_profiles (
        id, 
        email, 
        full_name, 
        phone_number, 
        birthdate, 
        sms_consent,
        created_at,
        updated_at
    )
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', ''),
        NEW.raw_user_meta_data->>'phone_number',
        (NEW.raw_user_meta_data->>'birthdate')::DATE,
        COALESCE((NEW.raw_user_meta_data->>'sms_consent')::BOOLEAN, FALSE),
        NOW(),
        NOW()
    );
    
    -- Create company if company_name is provided
    IF NEW.raw_user_meta_data->>'company_name' IS NOT NULL AND 
       NEW.raw_user_meta_data->>'company_name' != '' THEN
        DECLARE
            new_company_id UUID;
        BEGIN
            INSERT INTO companies (name, owner_id)
            VALUES (
                NEW.raw_user_meta_data->>'company_name',
                NEW.id
            )
            RETURNING id INTO new_company_id;
            
            -- Link user to company
            UPDATE user_profiles 
            SET company_id = new_company_id 
            WHERE id = NEW.id;
        END;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

-- Create trigger for new user signups
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user_signup();

-- Function to opt out of SMS
CREATE OR REPLACE FUNCTION opt_out_of_sms(user_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE user_profiles
    SET sms_consent = FALSE,
        sms_opt_out_at = NOW(),
        updated_at = NOW()
    WHERE id = user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to opt in to SMS
CREATE OR REPLACE FUNCTION opt_in_to_sms(user_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE user_profiles
    SET sms_consent = TRUE,
        sms_opt_out_at = NULL,
        updated_at = NOW()
    WHERE id = user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- RLS Policies for user_profiles
-- Users can read their own profile
CREATE POLICY "Users can view own profile"
    ON user_profiles FOR SELECT
    USING (auth.uid() = id);

-- Users can update their own profile
CREATE POLICY "Users can update own profile"
    ON user_profiles FOR UPDATE
    USING (auth.uid() = id);

-- RLS Policies for companies
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

-- Comment for documentation
COMMENT ON COLUMN user_profiles.full_name IS 'User full name collected at signup';
COMMENT ON COLUMN user_profiles.phone_number IS 'User phone number for SMS notifications (E.164 format recommended)';
COMMENT ON COLUMN user_profiles.birthdate IS 'User birthdate (must be 18+ to sign up)';
COMMENT ON COLUMN user_profiles.sms_consent IS 'Whether user has consented to receive SMS notifications';
COMMENT ON COLUMN user_profiles.sms_opt_out_at IS 'Timestamp when user opted out of SMS (for compliance tracking)';
COMMENT ON COLUMN user_profiles.company_id IS 'Company associated with this user';

