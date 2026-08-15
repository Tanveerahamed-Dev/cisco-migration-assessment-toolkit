export interface BoundedImageDimensions {
  readonly width?: number;
  readonly height?: number;
  readonly type: "png" | "svg";
}

export declare function imageSize(input: Uint8Array): BoundedImageDimensions;
export default imageSize;
