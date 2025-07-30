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

// SMITH token contract details
const SMITH_TOKEN_ADDRESS = "0x991ab5d07f28232ec1677e2c13239fb9b4b9ccb7";
const SMITH_TOKEN_ABI = [
  "function balanceOf(address owner) view returns (uint256)"
];
const SMITH_THRESHOLD = 250000;

export async function POST(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    const { walletAddress } = await request.json();
    
    if (!walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Wallet address is required" 
      }, { status: 400 });
    }
    
    // Check SMITH balance
    const provider = new ethers.JsonRpcProvider("https://mainnet.base.org");
    const smithContract = new ethers.Contract(
      SMITH_TOKEN_ADDRESS,
      SMITH_TOKEN_ABI,
      provider
    );
    
    const balanceBigInt = await smithContract.balanceOf(walletAddress);
    const balance = Number(ethers.formatUnits(balanceBigInt, 18));
    const meetsThreshold = balance >= SMITH_THRESHOLD;
    const formattedBalance = balance.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2
    });
    
    // Check if user exists
    const { data: existingUser } = await supabaseAdmin
      .from("neoguard_users")
      .select("id")
      .eq("wallet_address", walletAddress)
      .single();
    
    const userExists = !!existingUser;
    
    // Update user_wallets with the latest balance
    await supabaseAdmin
      .from("user_wallets")
      .upsert({
        wallet_address: walletAddress,
        smith_balance: balance,
        updated_at: new Date().toISOString()
      }, { onConflict: "wallet_address" });
    
    // If user exists, update their eligibility status
    if (userExists) {
      await supabaseAdmin
        .from("neoguard_users")
        .update({ 
          is_eligible: meetsThreshold,
          updated_at: new Date().toISOString()
        })
        .eq("wallet_address", walletAddress);
    }
    
    return NextResponse.json({
      success: true,
      userExists,
      isEligible: meetsThreshold,
      balance,
      formattedBalance,
      meetsThreshold
    });
  } catch (error) {
    console.error("Error checking eligibility:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 