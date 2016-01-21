/**
 *  Copyright (c) UWA, The University of Western Australia
 *  M468/35 Stirling Hwy
 *  Perth WA 6009
 *  Australia
 *
 *  All rights reserved
 *
 *  This library is free software; you can redistribute it and/or
 *  modify it under the terms of the GNU Lesser General Public
 *  License as published by the Free Software Foundation; either
 *  version 2.1 of the License, or (at your option) any later version.
 *
 *  This library is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 *  Lesser General Public License for more details.
 *
 *  You should have received a copy of the GNU Lesser General Public
 *  License along with this library; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place, Suite 330, Boston,
 *  MA 02111-1307  USA
 */
package org.icrar.awsChiles02.copyS3;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;

import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;

/**
 *
 */
public class GetMD5 {
  private static final Log LOG = LogFactory.getLog(GetMD5.class);

  public static void main(String[] args) throws Exception {
    for (String filename : args) {
      File file = new File(filename);
      if (file.isFile() && file.exists()) {
        String md5 = getFileChecksum(MessageDigest.getInstance("MD5"), file);
        LOG.info("MD5: " + md5);

        Files.write(Paths.get(filename + ".md5"), md5.getBytes());
      }
    }
  }

  /**
   * Calls to digest() return a decimal byte[], use this routine to convert to hex.
   *
   * @param bytes  has a decimal byte[]
   * @return <code>String</code> repesentation of array.
   */
  public static String digestDecimalToHex(byte[] bytes) {
    StringBuilder sb = new StringBuilder();
    for (byte aByte : bytes) {
      sb.append(Integer.toString((aByte & 0xff) + 0x100, 16).substring(1));
    }
    return sb.toString();
  }

  /**
   * Calculate the digest with nio
   * @param digest the type of message Digest to use
   * @param file the file to check
   * @return the MD5 as a hex string
   * @throws IOException
   */
  private static String getFileChecksum(MessageDigest digest, File file) throws IOException {
    FileInputStream f = new FileInputStream( file );
    FileChannel ch = f.getChannel( );
    byte[] byteArray = new byte[8388608];
    ByteBuffer bb = ByteBuffer.wrap( byteArray );
    int bytesCount;
    while ((bytesCount=ch.read( bb )) != -1) {
      digest.update(byteArray, 0, bytesCount);
      bb.clear( );
    }

    // Get the hash's bytes
    byte[] bytes = digest.digest();

    // This bytes[] has bytes in decimal format;
    // Convert it to hexadecimal format then return complete hash
    return digestDecimalToHex(bytes);
  }
}