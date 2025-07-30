/* eslint-disable */
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

export async function GET(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    // Get wallet address from query params
    const { searchParams } = new URL(request.url);
    const walletAddress = searchParams.get('walletAddress');
    
    if (!walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Wallet address is required" 
      }, { status: 400 });
    }
    
    // Get user's settings AND community information
    const { data: userAccount, error: userError } = await supabaseAdmin
      .from('neoguard_users')
      .select(`
        settings_id,
        address,
        name,
        telegram,
        discord,
        twitter,
        project_type,
        ticker,
        athena_secure_settings (
          id,
          use_global_blacklist,
          use_spam_detection,
          use_file_scanner,
          use_url_scanner,
          use_member_monitor
        )
      `)
      .eq('wallet_address', walletAddress)
      .single();
    
    if (userError) {
      return NextResponse.json({ 
        success: false, 
        message: "User not found" 
      }, { status: 404 });
    }
    
    const defaultSettings = {
      use_global_blacklist: false,
      use_spam_detection: false,
      use_file_scanner: false,
      use_url_scanner: false,
      use_member_monitor: false
    };
    
    const settings = [
      {
        id: 'use_global_blacklist',
        title: 'Global Blacklist',
        description: 'Leverage our network-wide database of malicious actors',
        // @ts-ignore
        enabled: userAccount?.athena_secure_settings?.use_global_blacklist ?? defaultSettings.use_global_blacklist,
        disabled: false
      },
      {
        id: 'use_spam_detection',
        title: 'Spam Detection',
        description: 'Enable advanced spam detection algorithms',
        // @ts-ignore
        enabled: userAccount?.athena_secure_settings?.use_spam_detection ?? defaultSettings.use_spam_detection,
        disabled: false
      },
      {
        id: 'use_member_monitor',
        title: 'Member Monitor',
        description: 'Monitor new members for suspicious activity. Enables 24-hour surveillance with temporary permission modifications to track name changes.',
        // @ts-ignore
        enabled: userAccount?.athena_secure_settings?.use_member_monitor ?? defaultSettings.use_member_monitor,
        disabled: false
      },
      {
        id: 'use_file_scanner',
        title: 'File Scanner (Coming Soon)',
        description: 'Scan uploaded files for potential threats',
        enabled: false,
        disabled: true
      },
      {
        id: 'use_url_scanner',
        title: 'URL Scanner (Coming Soon)',
        description: 'Scans URLs for wallet drainers, phishing activities and known malicious sites',
        enabled: false,
        disabled: true
      }
    ];
    
    // Extract community information
    const communityInfo = {
      address: userAccount?.address || '',
      name: userAccount?.name || '',
      telegram: userAccount?.telegram || '',
      discord: userAccount?.discord || '',
      twitter: userAccount?.twitter || '',
      project_type: userAccount?.project_type || '',
      ticker: userAccount?.ticker || ''
    };
    
    return NextResponse.json({
      success: true,
      data: {
        settings,
        settingsId: userAccount?.settings_id,
        communityInfo
      }
    });
  } catch (error) {
    console.error("Error getting settings:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 