import { NextResponse } from "next/server";
import { ethers } from "ethers";

export async function POST(request: Request) {
  try {
    const { walletAddress, signature, nonce } = await request.json();

    if (!walletAddress || !signature || !nonce) {
      return NextResponse.json(
        { success: false, message: "Missing required parameters" },
        { status: 400 }
      );
    }

    const message = `Sign this message to authenticate with NeoGuard: ${nonce}`;
    let isValid = false;

    const recoveredAddress = ethers.verifyMessage(message, signature);
    isValid = recoveredAddress.toLowerCase() === walletAddress.toLowerCase();

    if (!isValid) {
      return NextResponse.json(
        { success: false, message: "Invalid signature" },
        { status: 401 }
      );
    }

    return NextResponse.json({
      success: true,
      message: "Signature verified successfully",
    });
  } catch (error) {
    console.error("Verification error:", error);
    return NextResponse.json(
      { success: false, message: "Verification failed" },
      { status: 500 }
    );
  }
} 