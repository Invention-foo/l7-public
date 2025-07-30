import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

// Initialize Supabase admin client (server-side only)
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

// Make sure we have the required environment variables
if (!supabaseUrl || !supabaseServiceKey) {
  console.error("Missing Supabase environment variables");
}

const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

export async function POST(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    const { walletAddress, isEligible = true } = await request.json();
    
    if (!walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Wallet address is required" 
      }, { status: 400 });
    }
    
    // First, check if the wallet exists in user_wallets
    const { data: walletData, error: walletError } = await supabaseAdmin
      .from("user_wallets")
      .select("wallet_address")
      .eq("wallet_address", walletAddress)
      .single();
    
    if (walletError || !walletData) {
      // Wallet doesn't exist in user_wallets, so create it first
      const { error: insertWalletError } = await supabaseAdmin
        .from("user_wallets")
        .insert({
          wallet_address: walletAddress,
          chain_id: "0x14a33", // Base chain ID
          updated_at: new Date().toISOString()
        });
      
      if (insertWalletError) {
        console.error("Error creating wallet:", insertWalletError);
        return NextResponse.json({ 
          success: false, 
          message: "Failed to create wallet record" 
        }, { status: 500 });
      }
    }
    
    // Now get the exact wallet_address string from the database to ensure case match
    const { data: exactWallet } = await supabaseAdmin
      .from("user_wallets")
      .select("wallet_address")
      .eq("wallet_address", walletAddress)
      .single();
    
    if (!exactWallet) {
      return NextResponse.json({ 
        success: false, 
        message: "Failed to retrieve wallet record" 
      }, { status: 500 });
    }
    
    const exactWalletAddress = exactWallet.wallet_address;
    
    // Check if user already exists
    const { data: existingUser } = await supabaseAdmin
      .from("neoguard_users")
      .select("id, settings_id")
      .eq("wallet_address", exactWalletAddress)
      .single();
    
    if (existingUser) {
      return NextResponse.json({ 
        success: true,
        message: "User already exists",
        userCreated: false,
        userId: existingUser.id,
        settingsId: existingUser.settings_id
      });
    }
    
    // Create settings record first
    const { data: settingsData, error: settingsError } = await supabaseAdmin
      .from("athena_secure_settings")
      .insert({
        use_global_blacklist: true,
        use_spam_detection: true,
        use_file_scanner: false,
        use_url_scanner: false,
        use_member_monitor: true
      })
      .select("id")
      .single();
    
    if (settingsError) {
      console.error("Error creating settings:", settingsError);
      return NextResponse.json({ 
        success: false, 
        message: "Failed to create settings record" 
      }, { status: 500 });
    }
    
    // Create new user with the exact wallet address from user_wallets and the new settings ID
    const { data: userData, error } = await supabaseAdmin
      .from("neoguard_users")
      .insert({
        wallet_address: exactWalletAddress,
        is_eligible: isEligible,
        settings_id: settingsData.id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      })
      .select("id")
      .single();
    
    if (error) {
      // If user creation fails, clean up the settings record
      await supabaseAdmin
        .from("athena_secure_settings")
        .delete()
        .eq("id", settingsData.id);
      
      console.error("Error creating user:", error);
      return NextResponse.json({ 
        success: false, 
        message: "Database error" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      message: "User account created successfully",
      userCreated: true,
      userId: userData.id,
      settingsId: settingsData.id
    });
  } catch (error) {
    console.error("Error creating user account:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 