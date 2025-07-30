import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { ethers } from 'ethers';

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
    
    // Get request body
    const body = await request.json();
    const { walletAddress, settingsId, settingName, value, signature, message, timestamp } = body;
    
    if (!walletAddress || !settingsId || !settingName || value === undefined || !signature || !message || !timestamp) {
      return NextResponse.json({ 
        success: false, 
        message: "Missing required fields" 
      }, { status: 400 });
    }
    
    // Verify the signature
    const expectedMessage = `Update setting ${settingName} to ${value} at timestamp ${timestamp}`;
    if (message !== expectedMessage) {
      return NextResponse.json({ 
        success: false, 
        message: "Invalid message format" 
      }, { status: 400 });
    }
    
    // Check if the timestamp is recent (within 5 minutes)
    const now = Date.now();
    if (now - timestamp > 5 * 60 * 1000) {
      return NextResponse.json({ 
        success: false, 
        message: "Signature expired" 
      }, { status: 400 });
    }
    
    // Verify the signature matches the wallet address
    const signerAddress = ethers.verifyMessage(message, signature);
    if (signerAddress.toLowerCase() !== walletAddress.toLowerCase()) {
      return NextResponse.json({ 
        success: false, 
        message: "Invalid signature" 
      }, { status: 401 });
    }
    
    // Verify the user exists and has access to this settings ID
    const { data: userAccount, error: userError } = await supabaseAdmin
      .from('neoguard_users')
      .select('settings_id')
      .eq('wallet_address', walletAddress)
      .single();
    
    if (userError || !userAccount) {
      return NextResponse.json({ 
        success: false, 
        message: "User not found" 
      }, { status: 404 });
    }
    
    if (userAccount.settings_id !== settingsId) {
      return NextResponse.json({ 
        success: false, 
        message: "Unauthorized access to settings" 
      }, { status: 403 });
    }
    
    // Update the setting
    const { error } = await supabaseAdmin
      .from('athena_secure_settings')
      .update({ [settingName]: value })
      .eq('id', settingsId);
    
    if (error) {
      return NextResponse.json({ 
        success: false, 
        message: "Error updating setting" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      message: "Setting updated successfully"
    });
  } catch (error) {
    console.error("Error updating setting:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 